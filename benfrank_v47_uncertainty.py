"""Development-only bias, probability and finite-sample conformal calibration."""
import math
import statistics

from benfrank_v44_calibration import fit_isotonic, calibrate
from benfrank_v45_backtest import stratum


def finite_quantile(values, coverage=.9):
    """Split-conformal order statistic ceil((n+1)*coverage), no interpolation."""
    if not values or not 0 < coverage < 1 or any(not math.isfinite(float(v)) for v in values):
        raise ValueError("FINITE_NONEMPTY_CALIBRATION_VALUES_REQUIRED")
    rank = math.ceil((len(values) + 1) * coverage)
    if rank > len(values):
        raise ValueError("INSUFFICIENT_FINITE_SAMPLE_FOR_REQUESTED_COVERAGE")
    return sorted(values)[rank - 1]


def fit(rows, coverage=.9):
    if len(rows) < 30:
        raise ValueError("AT_LEAST_30_DEVELOPMENT_GAMES_REQUIRED")
    if len({r["game_id"] for r in rows}) != len(rows):
        raise ValueError("ONE_DEVELOPMENT_OUTCOME_PER_GAME_REQUIRED")
    if any(r.get("partition") != "DEVELOPMENT" for r in rows):
        raise ValueError("NEW_TEST_OUTCOMES_MUST_NOT_ENTER_CALIBRATION")
    if any(not all(isinstance(r[k],(int,float)) and math.isfinite(r[k]) for k in ('mean','q05','q95','actual','p_over_raw'))
           or not 0<=r['p_over_raw']<=1 or r['q05']>r['q95'] or r['over_result'] not in (0,1) for r in rows):
        raise ValueError('FINITE_VALID_DEVELOPMENT_FORECASTS_AND_OUTCOMES_REQUIRED')
    strata={stratum(r) for r in rows}
    if len(strata)!=1:raise ValueError('CALIBRATION_REQUIRES_ONE_PLATFORM_MARKET_SCORING_CONTRACT_LINE_BAND')
    rows = sorted(rows, key=lambda r: (r['tipoff_utc'], r['game_id']))
    split = max(20, int(len(rows)*.6))
    split = min(split,len(rows)-10)
    parameter_fit,conformal = rows[:split],rows[split:]
    bias = statistics.median(r["actual"] - r["mean"] for r in parameter_fit)
    residuals = [max(r["q05"] + bias - r["actual"], r["actual"] - r["q95"] - bias, 0) for r in conformal]
    radius = finite_quantile(residuals, coverage)
    bins = fit_isotonic([(r["p_over_raw"], r["over_result"]) for r in parameter_fit])
    prior = (sum(r["over_result"] for r in parameter_fit) + 1) / (len(parameter_fit) + 2)
    return {"method": "DEVELOPMENT_ONLY_SPLIT_CONFORMAL_AND_SHRUNK_ISOTONIC",
            "stratum":list(next(iter(strata))),
            "coverage": coverage, "bias_points": bias, "conformal_radius": radius,
            "isotonic_bins": bins, "probability_prior": prior,
            "probability_shrink_weight": len(parameter_fit) / (len(parameter_fit) + 20),
            "parameter_fit_games": [r['game_id'] for r in parameter_fit],
            "conformal_calibration_games": [r['game_id'] for r in conformal],
            "conformal_calibration_n": len(conformal),
            "development_n": len(rows), "development_game_ids": sorted(r["game_id"] for r in rows),
            "latest_development_tipoff": max(r["tipoff_utc"] for r in rows),
            "guarantee_scope": "Finite-sample conformal interpretation requires exchangeability; temporal/season shifts are evaluated, not assumed away.",
            "certification": "NOT_CERTIFIED"}


def apply(row, model):
    if not isinstance(row.get('p_over_raw'),(int,float)) or not math.isfinite(row['p_over_raw']) or not 0<=row['p_over_raw']<=1:
        raise ValueError('FINITE_VALID_RAW_PROBABILITY_REQUIRED')
    if list(stratum(row))!=model['stratum']:raise ValueError('CALIBRATION_SCOPE_MISMATCH')
    if row.get('game_id') in model['development_game_ids']:raise ValueError('DEVELOPMENT_GAME_IS_NOT_A_NEW_TEST')
    if row.get('tipoff_utc','')<=model['latest_development_tipoff']:raise ValueError('CALIBRATION_MUST_PRECEDE_PREDICTED_GAME')
    weight = model["probability_shrink_weight"]
    p = weight * calibrate(row["p_over_raw"], model["isotonic_bins"]) + (1 - weight) * model["probability_prior"]
    return {**row, "mean_adjusted": max(0, row["mean"] + model["bias_points"]),
            "q05_adjusted": max(0, row["q05"] + model["bias_points"] - model["conformal_radius"]),
            "q95_adjusted": max(0, row["q95"] + model["bias_points"] + model["conformal_radius"]),
            "p_over_calibrated": p}


def wilson(successes, total, z=1.959963984540054):
    if not 0 <= successes <= total or not total:
        raise ValueError("VALID_BINOMIAL_COUNTS_REQUIRED")
    p = successes / total
    denominator = 1 + z*z/total
    center = (p + z*z/(2*total)) / denominator
    half = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / denominator
    return [max(0, center-half), min(1, center+half)]
