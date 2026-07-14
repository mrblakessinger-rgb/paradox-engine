# GitHub — your first steps in this realm

You now have **3 real-world demos**. Next is people + a real repo.

**Goal today/tomorrow:** find one issue → leave one good comment (or open a tiny PR if it’s clear).  
**Not the goal:** dump Soft Pack / DNA into someone else’s project.

---

## Step 0 — Account (2 min)

1. Go to https://github.com — sign in (or create account).  
2. Optional: set a short bio: `Python · multi-agent reliability · health under load`  
3. Keep Gumroad out of bio until you’ve made 1–2 helpful comments (less spammy).

---

## Step 1 — Open the search (1 min)

**Start here (best first door):**  
https://github.com/search?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22+retry+OR+timeout+OR+backoff+language%3APython&type=issues

**Backup searches:**  
https://github.com/search?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22+rate+limit+OR+429+language%3APython&type=issues  

https://github.com/search?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22+language%3APython&type=issues  

Full list: `ops/FREE_PORTFOLIO_PRS.md`

---

## Step 2 — Pick ONE issue (10 min)

Click 5–8 issues. Choose one where:

- [ ] Still **Open**  
- [ ] Description is understandable in plain English  
- [ ] Looks like **retry / timeout / backoff / rate limit / error handling** (or small clear bug)  
- [ ] Not already claimed by 5 people fighting  
- [ ] Repo has recent commits (not dead 4 years)  

**Write down:**
```
Repo: _______________
Issue #: _______________
URL: _______________
One-sentence problem: _______________
```

---

## Step 3 — Read the room (5 min)

On that issue page:

1. Read full description + existing comments.  
2. Skim README of the repo (what the project is).  
3. If there’s a CONTRIBUTING.md, open it.

---

## Step 4 — Leave a comment (the exposure move)

Paste and edit:

```
Hi — I'd like to help with this.

My reading of the problem: [one sentence in your words].

Proposed approach:
1. [first small step]
2. [second step]
3. Add/adjust a test if the repo has tests

I can open a PR in the next few days if that direction sounds right.
Happy to change plan based on maintainer preference.
```

**Do:** be short, concrete, polite.  
**Don’t:** link Soft Pack, talk about swarms/DNA, or promise a rewrite of their architecture.

Click **Comment**.

Log in `ops/DAILY_LOG.md`:
```
Touches: 1 GitHub comment on <url>
```

---

## Step 5 — If they say “go ahead” (or silence + clear issue)

1. Fork the repo (button **Fork**).  
2. Clone your fork locally.  
3. Create a branch: `git checkout -b fix/retry-timeout` (name matches work).  
4. Make the **smallest** change that solves the issue.  
5. Run their tests if documented.  
6. Push + **Open pull request** → fill template → link `Fixes #123`.

If stuck mid-code, paste the issue URL + error here and we’ll plan the patch (still no Soft Pack dump).

---

## How this connects to Soft Pack (private)

| You see on GitHub | Soft Pack muscle |
|-------------------|------------------|
| 429 / rate limit | cool thrash / Proof C |
| retry storms | job queue real-world demo |
| flaky tools | tool fleet demo |
| quarantine bad workers | actuate quarantine |

In public PRs: only **their** code patterns.

---

## Success for this session

- [x] 3 real-world demos exist  
- [ ] GitHub account ready  
- [ ] One issue bookmarked  
- [ ] One comment posted  

That’s real realm exposure. PR can wait until the comment gets a reply (or 48h of silence on a clear good-first-issue).
