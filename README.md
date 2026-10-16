# Job Radar

Every morning this finds new AI Engineer, Python Backend, and Forward Deployed Engineer
openings in Bangalore, Chennai, and 100% remote (open to India), filters out anything
below 6 LPA, scores each job against your resume with AI, checks the company's hiring
trend, and publishes a web page you can open at 9 AM.

It does not apply for you. Each job has an "Open job posting" button and a ready-made
note for the recruiter, so applying to the day's best 5-10 takes about 15 minutes.

## How it works

1. **Collect**: LinkedIn, Indeed and Naukri listings through JobSpy (a free, open-source
   library), plus company careers pages (Greenhouse, Lever, Ashby) read directly through
   their public job feeds. No paid services anywhere.
2. **Filter**: role, city or remote, experience (skips roles needing 4+ years), and salary.
   Postings that list pay below 6 LPA are dropped. Most postings hide pay, so the AI
   estimates a range and the job is kept only if the estimated minimum is 6 LPA or more.
   Estimated salaries are clearly marked on the page. Change this in `config.yaml`
   (`salary.undisclosed`).
3. **Score**: Gemini (free tier) rates each job 0-100 against `profile.md`, lists your
   matching skills and gaps, and writes a short recruiter note using only facts from
   your profile. Jobs below 65 are dropped.
4. **Hiring trend**: history is saved in `data/history.json`, so the page shows whether a
   company is posting more or fewer roles over time. It says "Tracking" for the first
   two weeks while history builds up.
5. **Publish**: the page goes to Netlify. Your "applied" marks are saved in your browser.

## One-time setup (about 20 minutes)

### 1. Create a private GitHub repo
Create a new **private** repository (no README) and push these files with git, because
web drag-and-drop often skips the hidden `.github` folder. Keep it private: `profile.md`
contains your resume details.

    cd job-radar
    git init
    git add .
    git commit -m "first"
    git branch -M main
    git remote add origin https://github.com/<your-username>/job-radar.git
    git push -u origin main

### 2. Get the keys
- **Gemini**: create an API key in Google AI Studio (aistudio.google.com).
- **Netlify**: in Netlify, create a new site with "Deploy manually" (drop any small
  folder). Copy its Site ID from Site configuration. Then create a personal access
  token under User settings, Applications.

### 3. Add them as repo secrets
In GitHub: Settings, Secrets and variables, Actions, New repository secret.
Add `GEMINI_API_KEY`, `NETLIFY_AUTH_TOKEN`, `NETLIFY_SITE_ID`.
Also: Settings, Actions, General, Workflow permissions: choose "Read and write permissions".

### 4. Check the company list
On your computer: `pip install -r requirements.txt` then `python -m src.check_companies`.
Delete the lines marked FAIL in `companies.yaml` and add companies you want to track.

### 5. Do a test run
In GitHub, open Actions, "Daily job radar", "Run workflow". After it finishes, open your
Netlify site URL. Bookmark it. From now on it updates every morning.

## Timing
The workflow is scheduled for 8:00 AM IST because GitHub sometimes starts scheduled
jobs 5-30 minutes late, and scraping takes a few minutes. That way the page is ready by 9.

## Costs
Everything is free: GitHub Actions (private repos get 2,000 minutes a month; this uses
about 300), Gemini's free tier (about 40 scored jobs a day; lower `max_jobs_per_day` if
you hit limits), JobSpy, and Netlify.

## Tuning
Everything is in `config.yaml`: the job-site searches, role keywords, excluded title words, cities, experience
limit, minimum salary, how hidden salaries are handled, AI model, minimum fit score.
Update `profile.md` when your resume changes. If a model name stops working, check the
current name in Google AI Studio and update `gemini_model`.

## Test offline
`python -m src.main --mock --no-llm` builds `site/index.html` from sample jobs.
`python -m pytest tests` checks the salary and experience parsers.

## Notes
- Job sites sometimes block automated searches, LinkedIn especially. When a site returns
  nothing, the page tells you at the top; it usually recovers by itself. Fewer searches
  or a longer `delay_seconds` helps.
- Collecting LinkedIn listings automatically is against LinkedIn's terms even without
  logging in. JobSpy never uses your account, so your profile isn't at risk.
- The Netlify URL is not listed or indexed by search engines, but anyone with the link
  can open it. Don't share it.
- Estimated salaries and hiring trends are signals, not facts. Confirm pay with the recruiter.
