def money(cents):
    """Format an integer number of cents as $D.CC."""
    dollars = cents // 100
    remainder = cents % 100
    return f"${dollars}.{remainder}"
