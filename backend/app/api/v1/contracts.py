import hashlib
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_role
from app.db.enums import ContractStatus, ContractType, ExtractionJobStatus, UserRole
from app.db.models import Contract, ExtractionJob, User
from app.schemas.contract import (
    ContractDetail,
    ContractStatusResponse,
    ContractSummary,
    ContractUploadResponse,
    ExtractionJobSummary,
)
from app.services.file_validation import (
    MAX_UPLOAD_SIZE_BYTES,
    FileTooLargeError,
    UnsupportedFileTypeError,
    detect_file_kind,
    enforce_size_limit,
)
from app.services.ingestion import ingest_contract_document
from app.services.storage import save_contract_file

router = APIRouter(prefix="/contracts", tags=["contracts"])

_EDITOR_ROLES = (UserRole.ADMIN, UserRole.LEGAL_OPS)


async def _get_org_contract(
    db: DbSession, current_user: CurrentUser, contract_id: uuid.UUID
) -> Contract:
    contract = await db.get(Contract, contract_id)
    if contract is None or contract.org_id != current_user.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found.")
    return contract


@router.post(
    "", response_model=ContractUploadResponse, status_code=status.HTTP_201_CREATED
)
async def upload_contract(
    db: DbSession,
    current_user: Annotated[User, Depends(require_role(*_EDITOR_ROLES))],
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    contract_type: Annotated[ContractType, Form()] = ContractType.OTHER,
) -> ContractUploadResponse:
    data = await file.read(MAX_UPLOAD_SIZE_BYTES + 1)

    try:
        enforce_size_limit(data)
        file_kind = detect_file_kind(data)
    except FileTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)
        ) from exc
    except UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from exc

    file_hash = hashlib.sha256(data).hexdigest()
    existing = await db.execute(
        select(Contract.id).where(
            Contract.org_id == current_user.org_id, Contract.file_hash == file_hash
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This exact file has already been uploaded to your organization.",
        )

    resolved_title = title or Path(file.filename or "Untitled Contract").stem

    contract = Contract(
        org_id=current_user.org_id,
        uploaded_by=current_user.id,
        title=resolved_title,
        contract_type=contract_type,
        original_filename=file.filename or "upload",
        storage_path="",  # set below, once we know the contract's id
        file_hash=file_hash,
        status=ContractStatus.PROCESSING,
    )
    db.add(contract)
    await db.flush()

    contract.storage_path = save_contract_file(
        org_id=current_user.org_id, contract_id=contract.id, file_kind=file_kind, data=data
    )

    extraction_job = ExtractionJob(contract_id=contract.id, status=ExtractionJobStatus.QUEUED)
    db.add(extraction_job)
    await db.flush()

    await ingest_contract_document(
        db, contract=contract, extraction_job=extraction_job, file_kind=file_kind, data=data
    )

    await db.commit()
    await db.refresh(contract)

    return ContractUploadResponse(
        contract=ContractDetail.model_validate(contract), extraction_job_id=extraction_job.id
    )


@router.get("", response_model=list[ContractSummary])
async def list_contracts(
    db: DbSession,
    current_user: CurrentUser,
    status_filter: Annotated[ContractStatus | None, Query(alias="status")] = None,
    contract_type: Annotated[ContractType | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Contract]:
    query = select(Contract).where(Contract.org_id == current_user.org_id)
    if status_filter is not None:
        query = query.where(Contract.status == status_filter)
    if contract_type is not None:
        query = query.where(Contract.contract_type == contract_type)
    query = query.order_by(Contract.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{contract_id}", response_model=ContractDetail)
async def get_contract(
    db: DbSession, current_user: CurrentUser, contract_id: uuid.UUID
) -> Contract:
    return await _get_org_contract(db, current_user, contract_id)


@router.get("/{contract_id}/status", response_model=ContractStatusResponse)
async def get_contract_status(
    db: DbSession, current_user: CurrentUser, contract_id: uuid.UUID
) -> ContractStatusResponse:
    contract = await _get_org_contract(db, current_user, contract_id)

    result = await db.execute(
        select(ExtractionJob)
        .where(ExtractionJob.contract_id == contract.id)
        .order_by(ExtractionJob.started_at.desc().nullslast())
        .limit(1)
    )
    latest_job = result.scalar_one_or_none()

    return ContractStatusResponse(
        contract_id=contract.id,
        contract_status=contract.status,
        latest_extraction_job=(
            ExtractionJobSummary.model_validate(latest_job) if latest_job is not None else None
        ),
    )


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contract(
    db: DbSession,
    current_user: Annotated[User, Depends(require_role(*_EDITOR_ROLES))],
    contract_id: uuid.UUID,
) -> None:
    contract = await _get_org_contract(db, current_user, contract_id)
    await db.delete(contract)
    await db.commit()
