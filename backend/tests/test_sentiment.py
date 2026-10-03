from premium import sentiment as s


def test_tone_topic_and_the_words_that_decided_it():
    r = s.read("TCS net profit up 9%, board declares dividend")
    assert r["tone"] == "Positive" and r["topic"] == "Results" and "dividend" in r["positive_words"]
    assert s.read("Company faces SEBI probe and penalty")["tone"] == "Negative"
    assert s.read("Profit rises but SEBI issues penalty")["tone"] == "Mixed"
    assert s.read("Board meeting on 12 Oct")["tone"] == "Neutral"
    assert s.read("")["topic"] == "General"


def test_words_must_start_at_a_word_boundary_and_summary_counts():
    assert s.read("Stand-by arrangement")["tone"] == "Neutral"   # "ban" inside "stand-by" is not a match... (preceded by letter)
    items = [{"sentiment": s.read(t)} for t in ("record profit", "fraud probe", "meeting")]
    out = s.summarize(items)
    assert out["counts"] == {"Positive": 1, "Negative": 1, "Mixed": 0, "Neutral": 1} and out["overall"] == "Mixed" and "wrong" in out["note"]
    assert s.summarize([])["overall"] == "None"


def test_a_deal_topic_is_not_a_tone_and_boilerplate_is_removed():
    from premium import announcements as an

    assert s.read("Company has informed the Exchange about Acquisition")["tone"] == "Neutral"
    assert s.read("Acquisition")["topic"] == "Deal / order"
    t = an.parse([{"desc": "Press Release", "attchmntText": "Tata Consultancy Services Limited has informed the Exchange regarding a press release dated October 01, 2026"}])[0]["title"]
    assert t == "Press Release: A press release dated October 01, 2026"
