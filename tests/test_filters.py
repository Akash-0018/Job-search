from src.filters import parse_salary_lpa, parse_experience

def test_salary():
    assert parse_salary_lpa("8-14 Lacs P.A.") == (8, 14)
    assert parse_salary_lpa("₹6,00,000 - ₹9,00,000 a year") == (6, 9)
    assert parse_salary_lpa("10-18 LPA") == (10, 18)
    assert parse_salary_lpa("INR 8L - 12L") == (8, 12)
    assert parse_salary_lpa("₹ 6.5 Lakhs") == (6.5, 6.5)
    assert parse_salary_lpa("$20K - $30K") == (16.8, 25.2)
    assert parse_salary_lpa("₹50,000 per month") == (6.0, 6.0)
    assert parse_salary_lpa("Not Disclosed") == (None, None)
    assert parse_salary_lpa("") == (None, None)
    assert parse_salary_lpa("1200000-1800000 INR YEAR") == (12, 18)

def test_experience():
    assert parse_experience("1-3 Yrs", "") == (1, 3)
    assert parse_experience("", "Need 5+ years of experience in Python") == (5, None)
    assert parse_experience("2 to 4 years", "") == (2, 4)
    assert parse_experience("", "Great team culture") == (None, None)


def test_jobspy_rows():
    from src.sources.jobspy_source import row_to_job
    from src.filters import parse_salary_lpa
    nan = float("nan")
    j = row_to_job({"title": "AI Engineer", "job_url": "https://x/1", "company": "Acme",
                    "location": "Bengaluru, Karnataka, India", "min_amount": 800000.0,
                    "max_amount": 1400000.0, "currency": "INR", "interval": "yearly",
                    "is_remote": nan, "experience_range": "1-3 Yrs", "description": nan,
                    "date_posted": "2026-10-15", "work_from_home_type": "Hybrid"}, "naukri")
    assert j.source == "Naukri" and not j.remote and j.description == ""
    assert parse_salary_lpa(j.salary_text) == (8, 14)
    m = row_to_job({"title": "LLM Eng", "job_url": "u", "min_amount": 50000.0, "max_amount": nan,
                    "currency": "INR", "interval": "monthly", "is_remote": True}, "linkedin")
    assert m.remote and parse_salary_lpa(m.salary_text) == (6, 6)
    assert row_to_job({"title": nan, "job_url": "u"}, "indeed") is None
