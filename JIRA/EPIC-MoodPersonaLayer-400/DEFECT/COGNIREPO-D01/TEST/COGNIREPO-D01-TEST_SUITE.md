# COGNIREPO-D01 — Manual test suite

## TC-D01-1: Clear persona after setting one
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: defect fix merged.
- What to do: set persona=caveman, confirm active; clear via persona="none"; confirm reverted.
- Prompt: "Set my persona to caveman, then clear it back to default."
- Expected results: after clearing, get_user_profile() has no active_persona/persona_behavior/
  output_contract keys — identical to a profile that never had a persona set.
- Obtained results: ran the mechanics directly on cognirepo_test_repo/medium/ansible: set
  persona=caveman → active_persona="caveman"; cleared via persona="none" →
  {"recorded": true, "cleared": true}; profile afterward has active_persona/persona_behavior/
  output_contract all None — matches the never-set baseline exactly.
- Verdict: PASS

## TC-D01-2: Clearing when nothing was set is a no-op
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/dummy
- Prerequisites: defect fix merged; fresh repo, no persona ever set.
- What to do: call record_user_preference("persona","none").
- Prompt: "Clear my persona preference."
- Expected results: recorded true, no error, profile unaffected.
- Obtained results: ran on cognirepo_test_repo/dummy (fresh, no persona ever set):
  record_user_preference("persona","none") → {"recorded": true, "cleared": true}, no error;
  active_persona stayed None.
- Verdict: PASS
