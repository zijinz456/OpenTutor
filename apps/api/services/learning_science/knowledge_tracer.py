"""Simplified Bayesian Knowledge Tracing (BKT).

Estimates probability of mastery P(L_n) for a knowledge point based on
the student's answer sequence.  Four parameters:

- P(L0): Prior probability the student already knows the concept
- P(T):  Probability of learning the concept on each opportunity
- P(G):  Probability of guessing correctly without knowing
- P(S):  Probability of slipping (answering wrong despite knowing)

Reference: Corbett & Anderson (1994), "Knowledge tracing: Modeling the
acquisition of procedural knowledge".

The implementation uses per-student/knowledge-point parameter personalisation
derived from the answer history rather than static global constants.
"""

import logging
import uuid
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Default BKT parameters (tuned for typical educational content)
_DEFAULT_P_L0 = 0.10   # Low prior — assume student doesn't know initially
_DEFAULT_P_T = 0.20     # 20% chance of learning on each opportunity
_DEFAULT_P_G = 0.25     # Guess rate for 4-option MC (1/4)
_DEFAULT_P_S = 0.10     # 10% slip rate


@dataclass
class BKTParams:
    """BKT parameter set for a knowledge point."""
    p_l0: float = _DEFAULT_P_L0
    p_t: float = _DEFAULT_P_T
    p_g: float = _DEFAULT_P_G
    p_s: float = _DEFAULT_P_S


@dataclass
class BKTState:
    """Current BKT state for a student–knowledge point pair."""
    p_mastery: float = _DEFAULT_P_L0  # P(L_n) — current mastery estimate
    observations: int = 0


def estimate_params(
    results: list[bool],
    question_type: str | None = None,
) -> BKTParams:
    """Estimate BKT parameters from answer history.

    Uses simple heuristics to personalise defaults:
    - P(L0): from first-attempt correctness
    - P(T): from consecutive-correct transitions
    - P(G): from question type (MC=0.25, TF=0.5, else 0.1)
    - P(S): from high-mastery-still-wrong frequency
    """
    if not results:
        return BKTParams()

    # P(G) — guess probability based on question type
    p_g = _DEFAULT_P_G
    if question_type:
        qt = question_type.lower()
        if qt in ("tf", "true_false"):
            p_g = 0.50
        elif qt in ("mc", "multiple_choice", "select_all"):
            p_g = 0.25
        elif qt in ("short_answer", "fill_blank", "free_response"):
            p_g = 0.05
        elif qt == "matching":
            p_g = 0.10

    # P(L0) — if first attempt is correct, higher prior
    p_l0 = 0.30 if results[0] else 0.05

    # P(T) — estimate from transitions (wrong → correct sequences)
    transitions = 0
    opportunities = 0
    for i in range(1, len(results)):
        if not results[i - 1]:  # Previous was wrong
            opportunities += 1
            if results[i]:  # Now correct → might have learned
                transitions += 1
    p_t = transitions / max(opportunities, 1) if opportunities > 0 else _DEFAULT_P_T
    p_t = max(0.05, min(p_t, 0.5))  # Clamp to reasonable range

    # P(S) — estimate from correct → wrong transitions among recent answers
    slips = 0
    slip_opportunities = 0
    for i in range(1, len(results)):
        if results[i - 1]:  # Previous was correct
            slip_opportunities += 1
            if not results[i]:  # Now wrong → slip
                slips += 1
    p_s = slips / max(slip_opportunities, 1) if slip_opportunities > 0 else _DEFAULT_P_S
    p_s = max(0.02, min(p_s, 0.3))  # Clamp

    return BKTParams(p_l0=p_l0, p_t=p_t, p_g=p_g, p_s=p_s)


def update_mastery(
    state: BKTState,
    is_correct: bool,
    params: BKTParams,
) -> BKTState:
    """Update mastery estimate after one observation using Bayes' rule.

    Step 1: Posterior after evidence (correct/wrong)
        P(L_n | obs) = P(obs | L_n) * P(L_n) / P(obs)

    Step 2: Incorporate learning
        P(L_{n+1}) = P(L_n | obs) + (1 - P(L_n | obs)) * P(T)
    """
    p_l = state.p_mastery

    if is_correct:
        # P(correct | knows) = 1 - P(S)
        # P(correct | ~knows) = P(G)
        p_correct = p_l * (1 - params.p_s) + (1 - p_l) * params.p_g
        p_l_given_obs = (p_l * (1 - params.p_s)) / max(p_correct, 1e-9)
    else:
        # P(wrong | knows) = P(S)
        # P(wrong | ~knows) = 1 - P(G)
        p_wrong = p_l * params.p_s + (1 - p_l) * (1 - params.p_g)
        p_l_given_obs = (p_l * params.p_s) / max(p_wrong, 1e-9)

    # Incorporate learning opportunity
    p_l_new = p_l_given_obs + (1 - p_l_given_obs) * params.p_t

    # Clamp to [0, 1]
    p_l_new = max(0.0, min(1.0, p_l_new))

    return BKTState(
        p_mastery=p_l_new,
        observations=state.observations + 1,
    )


def compute_mastery_from_sequence(
    results: list[bool],
    question_type: str | None = None,
    params: BKTParams | None = None,
) -> float:
    """Compute P(L_n) from a full answer sequence.

    Convenience function that estimates params (if not provided) and
    runs the BKT forward algorithm over the sequence.
    """
    if not results:
        return 0.0

    if params is None:
        params = estimate_params(results, question_type)

    state = BKTState(p_mastery=params.p_l0)
    for correct in results:
        state = update_mastery(state, correct, params)

    return state.p_mastery


def compute_mastery_adaptive(
    results: list[bool],
    concept: str,
    user_id: "uuid.UUID",
    course_id: "uuid.UUID | None" = None,
    question_type: str | None = None,
) -> float:
    """Compute mastery using EM-trained pyBKT params when available.

    Transparently upgrades to trained parameters if the bkt_trainer has
    cached fitted params for this concept (requires >= 15 observations).
    Falls back to heuristic estimation otherwise.

    This is the recommended entry point for all mastery calculations.
    """
    try:
        from services.learning_science.bkt_trainer import get_trained_params

        trained = get_trained_params(user_id, course_id, concept)
        if trained:
            params = BKTParams(
                p_l0=trained["prior"],
                p_t=trained["learns"],
                p_g=trained["guesses"],
                p_s=trained["slips"],
            )
            return compute_mastery_from_sequence(results, question_type, params=params)
    except ImportError:
        pass
    except (KeyError, ValueError, RuntimeError) as e:
        logger.warning("Trained BKT param lookup failed for '%s': %s", concept, e)

    # Fallback to heuristic estimation
    return compute_mastery_from_sequence(results, question_type)
