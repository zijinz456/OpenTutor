"""Tests for services.agent.socratic_engine — SocraticEngine state machine."""

import pytest

from services.agent.socratic_engine import SocraticEngine, SocraticState


# ── Initial state selection ──


def test_initial_state_high_cognitive_load():
    """High cognitive load should start in SCAFFOLD."""
    engine = SocraticEngine(cognitive_load=0.8)
    assert engine.state == SocraticState.SCAFFOLD


def test_initial_state_low_mastery():
    """Low mastery (<0.3) should start in SCAFFOLD."""
    engine = SocraticEngine(mastery=0.2)
    assert engine.state == SocraticState.SCAFFOLD


def test_initial_state_high_mastery():
    """High mastery (>0.7) should start in PROBE."""
    engine = SocraticEngine(mastery=0.8)
    assert engine.state == SocraticState.PROBE


def test_initial_state_conceptual_error():
    """Conceptual errors should start in CONFRONT."""
    engine = SocraticEngine(mastery=0.5, error_type="conceptual")
    assert engine.state == SocraticState.CONFRONT


def test_initial_state_procedural_error():
    """Procedural errors should start in SCAFFOLD."""
    engine = SocraticEngine(mastery=0.5, error_type="procedural")
    assert engine.state == SocraticState.SCAFFOLD


def test_initial_state_default():
    """No special signals => CLARIFY."""
    engine = SocraticEngine(mastery=0.5, cognitive_load=0.3)
    assert engine.state == SocraticState.CLARIFY


# ── State transitions ──


def test_transition_probe_correct_goes_to_confirm():
    engine = SocraticEngine(state=SocraticState.PROBE)
    new = engine.transition("correct")
    assert new == SocraticState.CONFIRM


def test_transition_probe_wrong_goes_to_confront():
    engine = SocraticEngine(state=SocraticState.PROBE)
    new = engine.transition("wrong")
    assert new == SocraticState.CONFRONT


def test_transition_scaffold_correct_goes_to_probe():
    engine = SocraticEngine(state=SocraticState.SCAFFOLD)
    new = engine.transition("correct")
    assert new == SocraticState.PROBE


def test_transition_unknown_quality_defaults_to_scaffold():
    """Unknown response quality should fall back to SCAFFOLD."""
    engine = SocraticEngine(state=SocraticState.PROBE)
    new = engine.transition("gibberish")
    assert new == SocraticState.SCAFFOLD


def test_turns_in_state_increments_on_same_state():
    """Staying in the same state should increment turns_in_state."""
    engine = SocraticEngine(state=SocraticState.SCAFFOLD)
    engine.transition("wrong")  # SCAFFOLD -> SCAFFOLD
    assert engine.turns_in_state == 1
    engine.transition("wrong")
    assert engine.turns_in_state == 2


def test_turns_in_state_resets_on_state_change():
    """Changing state should reset turns_in_state to 0."""
    engine = SocraticEngine(state=SocraticState.SCAFFOLD, turns_in_state=3)
    engine.transition("correct")  # SCAFFOLD -> PROBE
    assert engine.turns_in_state == 0


# ── Prompt directive ──


def test_prompt_directive_contains_state_name():
    engine = SocraticEngine(state=SocraticState.CONFRONT)
    directive = engine.get_prompt_directive()
    assert "CONFRONT" in directive
    assert "counterexample" in directive.lower()


def test_prompt_directive_escape_hatch():
    """After MAX_SCAFFOLD_TURNS, directive should switch to direct explanation."""
    engine = SocraticEngine(state=SocraticState.SCAFFOLD, turns_in_state=5)
    directive = engine.get_prompt_directive()
    assert "direct explanation" in directive.lower()


# ── Serialization roundtrip ──


def test_to_dict_and_from_dict_roundtrip():
    engine = SocraticEngine(mastery=0.6, cognitive_load=0.4, error_type="conceptual",
                             state=SocraticState.CLARIFY, turns_in_state=2)
    data = engine.to_dict()
    restored = SocraticEngine.from_dict(data)
    assert restored.state == SocraticState.CLARIFY
    assert restored.turns_in_state == 2
    assert restored.mastery == 0.6
    assert restored.cognitive_load == 0.4
    assert restored.error_type == "conceptual"


def test_from_dict_missing_state_uses_initial():
    """from_dict with no state key should use _initial_state()."""
    restored = SocraticEngine.from_dict({"mastery": 0.9})
    assert restored.state == SocraticState.PROBE  # high mastery -> PROBE
