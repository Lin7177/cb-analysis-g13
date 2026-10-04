"""Terminal stock distributions: historical block bootstrap (primary) and zero-drift GBM (secondary)."""
import numpy as np

def bootstrap_log_returns(ret, n_paths, horizon_sessions, block=21, seed=0):
    """Circular block bootstrap of daily simple returns -> total log return per path.

    Blocks stay internally ordered, so volatility clustering and jumps inside a
    block survive; cross-path independence of blocks is an assumption.
    """
    if len(ret) < 2 * block:
        raise ValueError(f'insufficient history for block bootstrap: {len(ret)} returns < 2 x block {block}')
    rng = np.random.default_rng(seed)
    r = np.asarray(ret, dtype=float)
    n_blocks = int(np.ceil(horizon_sessions / block))
    starts = rng.integers(0, len(r), size=(n_paths, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % len(r)
    seq = np.log1p(r[idx]).reshape(n_paths, -1)[:, :horizon_sessions]
    return seq.sum(axis=1)

def gbm_log_returns(sigma, tau_years, n_paths, seed=0):
    """Exact terminal log return under zero drift (risk-neutral-ish view declared, not estimated)."""
    rng = np.random.default_rng(seed)
    return (-0.5 * sigma ** 2) * tau_years + sigma * np.sqrt(tau_years) * rng.standard_normal(n_paths)

def summarize(returns_pct, exit_values, threshold_call=130.0):
    """Distribution stats in return-percent space plus call-region probability of exit values."""
    q = np.percentile(returns_pct, [5, 25, 50, 75, 95])
    return dict(p05=q[0], p25=q[1], p50=q[2], p75=q[3], p95=q[4],
                mean=float(np.mean(returns_pct)), std=float(np.std(returns_pct, ddof=1)),
                p_loss=float(np.mean(returns_pct < 0) * 100), p_gt5=float(np.mean(returns_pct > 5) * 100),
                p_exit_gt130=float(np.mean(np.asarray(exit_values) > threshold_call) * 100))
