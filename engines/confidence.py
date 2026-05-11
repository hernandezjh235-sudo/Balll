def confidence_tier(edge):
    try:
        edge = float(edge)
    except Exception:
        return "PASS"

    if edge >= 15:
        return "ELITE"
    if edge >= 10:
        return "STRONG"
    if edge >= 5:
        return "MEDIUM"
    return "PASS"
