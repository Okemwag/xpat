# Using Xpat: a short guide

Xpat estimates flood losses for property portfolios in Nairobi and helps underwriters decide whether to write a risk. This
guide answers everyday questions. The method and its limits are in `docs/REPORT.md`.

## What Xpat does

You give Xpat a list of properties (a schedule, a broker document or a plain description). For each property it looks
up a flood-hazard score, turns it into an assumed depth and a share of value damaged, and adds the losses up. The result
is a loss curve showing the loss you might expect in a 1-in-10 up to a 1-in-10,000 year flood. It also shows the average
annual loss and where the loss concentrates. The results are indicative. They are not a price or underwriting advice.

## Creating an account

Open the app and choose **Sign in**. Then choose who you are:

- **Administrator, then Create an organisation.** For the first person from a company. You fill in your organisation's
  name, your name, your work e-mail and a password. The organisation is created and you are signed in straight away as
  its administrator (owner), with the head-of-underwriting role so you can use the model too.
- **User, then Request an account.** For people whose organisation already uses Xpat. You fill in your name, e-mail,
  password and the organisation code. An administrator approves your request and chooses your roles. You can sign in
  once it is approved, and you get an e-mail when it is.

There is no e-mail confirmation step. Passwords need at least 12 characters and are checked against known breaches.
Administrators are asked to set up two-step verification with an authenticator app the first time they sign in.

## The organisation code

Every organisation has a code that looks like ABCD-EFGH. Administrators find it in **Administration, Users &
invitations** and share it with colleagues. A person can register with any e-mail address, Gmail included, if they enter
the code. Without a code, a request reaches an organisation only when the person's work e-mail domain is one the
organisation accepts. A code does not give access by itself: an administrator still approves every request. If a code
was shared too widely, the administrator can replace it, and the old code stops working.

## Signing in

Use the address the app gives you (by default http://127.0.0.1:8501). Choose **User** or **Administrator** and sign in
with your e-mail and password. Administrators land on the administration pages. If you forget your password, use
**Forgot your password?** on the sign-in page. If sign-in says your request is waiting, an administrator has not approved
it yet. If your company uses Microsoft or Google sign-in, use the company sign-in link.

## Roles

- **Owner and admin:** manage members, roles, the organisation code, security, settings and the audit log. They do not run
  analyses unless they also hold a working role, which they can add to their own account in **Your own roles**.
- **Head of underwriting:** runs analyses, sets the underwriting rules and house assumptions, approves evidence and referrals.
- **Underwriter:** uploads schedules and documents, runs analyses, records underwriting decisions, exports reports.
- **Analyst:** as an underwriter, plus assumption sandboxes and sensitivity runs.
- **Reviewer:** approves or withdraws AI-extracted flood evidence.
- **Viewer:** reads results shared with them.
- **Auditor:** reads the audit log and run records.

## Running a portfolio

Go to **Portfolio**. You can:

- **Upload a file:** a CSV or Excel schedule with columns such as loc_id, lat, lon, housing_class and tiv_kes. A PDF or
  Word broker document is read by AI, with every value quoted from the document.
- **Describe in words:** for example "20 iron-sheet houses in Mathare worth 300,000 each". AI turns it into records.
- **Use the sample portfolio:** 600 synthetic Nairobi properties.

Before running, the **schedule check** flags likely data errors, such as duplicate IDs, swapped coordinates, values in
the wrong units or an unusual cost per square metre, and proposes fixes you can tick. You also say whether the data is
real or synthetic. Every result is labelled REAL or SYNTHETIC.

## Reading the results

- **Overview:** headline numbers, the loss curve, loss by construction type, where loss concentrates and the largest
  losses.
- **Loss curve:** loss against how rare the flood is. "1-in-100" means a loss at least this large has an assumed 1%
  chance in any year; it does not mean once every 100 years.
- **Accumulation map:** each property sized by value and coloured by hazard, with the full calculation in the tooltip.
- **Property explorer:** one property's hazard, assumed depth, damage share and loss in every scenario.

## Underwriting decisions

On **Underwriting decision**, enter the offered premium for 100% of the risk and the offered share. The organisation's
rules recommend accepting, taking a smaller share or declining. The page then shows:

- **Our advice:** one plain recommendation with reasons, conditions and how far to trust it.
- **Pricing and premium adequacy:** how the technical premium is built from the modelled annual loss, and whether the
  offered premium is adequate, thin or inadequate.
- **Accumulation:** the loss in each 1 km area for this risk and for what the organisation has already written, with
  warnings when an area is over its limit or one area holds too much of the risk.

AI can explain the recommendation and draft a referral note or quote letter, but it cannot change the recommendation. A
person records the decision. Overriding the rules needs a written reason.

## AI features and which model is used

AI reads documents and descriptions, extracts flood evidence from reports and news, explains results, answers questions
and drafts memos and public notes. Every figure it writes is checked against the model's own numbers. AI output never sets
a flood depth, damage ratio or loss directly.

Each person chooses **Google Gemini (cloud)** or **a local model on this server** in **Profile & security, AI model**,
within the models the organisation allows. If the organisation keeps client data on its own server, documents, schedules
and results on real exposure always use the local model.

## The Xpat assistant

The assistant on the home page and on Overview answers questions about Xpat, how to use it and how the model works. It
answers from Xpat's own documentation and lists the sections it used. On Overview, it can also answer about the results
you have loaded, using the same checked figures as the rest of the app. It says when the documentation does not cover a
question, flags any figure it cannot trace, and gives no binding, pricing or legal advice. When AI is off, it shows the
most relevant passage of the documentation instead. Visitors who are not signed in can ask a limited number of
questions per hour and never see any organisation's data.

## Privacy and security

E-mail addresses and phone numbers are removed from text before it is sent to an AI model. Uploaded documents are not
kept. Every sign-in and change is recorded in the organisation's audit log. Real client data stays inside the
organisation that uploaded it.

## What the model cannot do

The hazard is a proxy built from terrain and rivers. It cannot see blocked or overwhelmed drains, which cause much of
Nairobi's flooding. It flags 12 of 24 government-named flood areas on its own. Return periods are assumed, and the damage
curves are not calibrated to Kenyan claims. A zero hazard score means the map did not flag a place, not that it cannot
flood.
