from app.services.prefilter import classify_chunk, has_obligation_signal, is_boilerplate


def test_date_bearing_paragraph_passes_prefilter() -> None:
    assert has_obligation_signal("This Agreement expires on January 1, 2027.")


def test_duration_bearing_paragraph_passes_prefilter() -> None:
    assert has_obligation_signal("Either party may terminate with 60 days written notice.")


def test_currency_bearing_paragraph_passes_prefilter() -> None:
    assert has_obligation_signal("Licensee shall pay a fee of $10,000 upon execution.")


def test_keyword_bearing_paragraph_passes_prefilter() -> None:
    assert has_obligation_signal(
        "Each party agrees to maintain the confidentiality of Confidential Information."
    )


def test_boilerplate_paragraph_does_not_pass_prefilter() -> None:
    assert not has_obligation_signal("This Agreement is entered into by and between the parties.")


def test_witness_whereof_is_boilerplate() -> None:
    assert is_boilerplate(
        section_heading=None,
        raw_text="IN WITNESS WHEREOF, the parties have executed this Agreement.",
    )


def test_notary_block_is_boilerplate() -> None:
    assert is_boilerplate(section_heading=None, raw_text="Subscribed before me, a Notary Public.")


def test_definitions_heading_is_boilerplate_even_with_keywords() -> None:
    boilerplate, passed = classify_chunk(
        section_heading="1. DEFINITIONS",
        raw_text="'Termination Date' means the date on which this Agreement expires.",
    )
    assert boilerplate is True
    assert passed is False


def test_renewal_clause_under_normal_heading_passes() -> None:
    boilerplate, passed = classify_chunk(
        section_heading="TERM AND RENEWAL",
        raw_text="This Agreement renews automatically for successive 1 year terms unless "
        "either party gives 90 days written notice of non-renewal.",
    )
    assert boilerplate is False
    assert passed is True
