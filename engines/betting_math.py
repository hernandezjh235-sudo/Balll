def american_to_decimal(odds):
    odds = float(odds)
    if odds > 0:
        return 1 + odds / 100
    return 1 + 100 / abs(odds)

def expected_value(prob, american_odds=-110):
    dec = american_to_decimal(american_odds)
    return (prob * (dec - 1)) - (1 - prob)

def kelly_fraction(prob, american_odds=-110):
    dec = american_to_decimal(american_odds)
    b = dec - 1
    q = 1 - prob
    if b <= 0:
        return 0
    return max(((b * prob) - q) / b, 0)
