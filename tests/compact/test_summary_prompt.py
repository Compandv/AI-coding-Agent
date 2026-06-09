from mewcode.compact.summary_prompt import build_summary_prompt, extract_summary


def test_build_summary_prompt_contains_two_phase_tags_and_sections():
    prompt = build_summary_prompt([{"role": "user", "content": "帮我修 bug"}])

    assert "<analysis>" in prompt
    assert "<summary>" in prompt
    assert "## 1. Current Task Goal" in prompt
    assert "## 9. Constraints Modes Stored Paths And Precision Boundaries" in prompt
    assert "帮我修 bug" in prompt


def test_build_summary_prompt_includes_user_focus():
    prompt = build_summary_prompt(
        [{"role": "user", "content": "old"}],
        focus="重点保留第八章 context.py 实现细节",
    )

    assert "[user supplied compact focus]" in prompt
    assert "重点保留第八章 context.py 实现细节" in prompt


def test_extract_summary_prefers_summary_tag():
    raw = "<analysis>scratch</analysis><summary>final</summary>"

    assert extract_summary(raw) == "final"


def test_extract_summary_keeps_final_summary_compatibility():
    raw = "<analysis>scratch</analysis><final_summary>legacy final</final_summary>"

    assert extract_summary(raw) == "legacy final"
