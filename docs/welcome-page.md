# The information page (and keeping bots out)

A page about CoachQuest to send to people before they sign up. It covers what CoachQuest does,
with screenshots, a "how it works" diagram, a short note on their data, and Sign up / Sign in
buttons.

## Using it

1. **Admin → Information page:** tick **Page is on**.
2. **Copy the link** (`https://<your site>/welcome/<secret>`) and send it to people.
3. **Edit the title and text.** The text is Markdown; `[[how-it-works]]` is where the diagram goes.
4. **Add screenshots:** use **Add a screenshot** (PNG, JPEG or WebP, up to 5 MB). It goes in where
   your cursor is, as `![caption](welcome-img/…)`. The caption shows under the picture.
5. **New link:** makes the old link stop working, for everyone. Use it if a link has spread
   further than you wanted.

While the page is off, or with a wrong or old link, people see "This page isn't available".

## What keeps bots and search engines away

**In CoachQuest (nothing to do):**

- **The link has a secret part** and nothing on the site links to it.
- **Every page carries "don't index".** That's three signals: a `noindex, nofollow, noarchive`
  header (`X-Robots-Tag`), a `<meta name="robots">` tag, and a `robots.txt` that disallows
  everything. Google, Bing and the AI crawlers that follow the rules then skip the site.
- **nginx limits the information page** to about 30 requests a minute per visitor.
- **Referrers stay on the site** (`Referrer-Policy: same-origin`), so the secret link doesn't leak
  to sites people click through to.

**In Cloudflare (the site is behind its orange-cloud proxy; menu names change now and then):**

1. **Security → Bots:** turn on **Bot Fight Mode**. On paid plans the equivalent is **Super Bot
   Fight Mode**: set "Definitely automated" to Block.
2. **Block AI crawlers:** in the same area, or under **AI Crawl Control**, turn on blocking
   for AI scrapers and crawlers.
3. **A human check on the information page:** go to **Security → WAF → Custom rules → Create rule**.
   - Name: `CoachQuest information page`
   - Field **URI Path**, operator **starts with**, value `/welcome/`
   - Action: **Managed Challenge**

   People get a quick (usually invisible) check before the page opens, and bots are stopped.
   Leave `/api/` out of this rule: the page itself calls `/api/welcome/…` once the check has passed.
4. Optionally, a **Rate limiting rule** for `/welcome/` (e.g. 20 requests a minute per IP).

Bot Fight Mode can also slow down calls from servers. Strava's, Garmin's and Intervals.icu's
sign-in pages send the *browser* back to CoachQuest, so they're fine. If Strava webhooks are
added later, allow Strava there with a WAF skip rule.
