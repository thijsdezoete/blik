# Admin Guide

Complete guide for administrators setting up and managing the 360 feedback system.

## Table of Contents

- [Initial Setup](#initial-setup)
- [Organization Settings](#organization-settings)
- [Who Can See What](#who-can-see-what)
- [Managing Reviewees](#managing-reviewees)
- [Org Chart](#org-chart)
- [Creating Review Cycles](#creating-review-cycles)
- [Managing Invitations](#managing-invitations)
- [Closing Cycles & Generating Reports](#closing-cycles--generating-reports)
- [Questionnaire Management](#questionnaire-management)

---

## Initial Setup

### First-Time Setup Wizard

1. **Access the setup wizard** at `/setup/` when first deploying
2. **Create admin account** - Username and password for system administration
3. **Configure organization** - Name and contact email
4. **Set email settings** - SMTP configuration for notifications
5. **Optional: Generate test data** - Creates sample reviewees and cycles to explore the system

### Post-Setup Access

After setup, access the admin dashboard at `/dashboard/`

---

## Organization Settings

Navigate to **Dashboard → Settings** to configure:

### Organization Details
- **Organization Name** - Displayed in emails and reports
- **Contact Email** - Primary organization contact

### Email (SMTP) Settings
- **SMTP Host** - Your email server (e.g., `smtp.gmail.com` or `host.docker.internal` for local Mailpit)
- **SMTP Port** - Common ports: 587 (TLS), 465 (SSL), 25 (Plain)
- **SMTP Username** - Authentication username (usually your email)
- **SMTP Password** - Authentication password or app-specific password
- **Use TLS** - Enable for port 587 (recommended)
- **From Email** - Email address shown as sender in notifications

**Important:** Settings are stored in the database and persist across container restarts. Changes take effect immediately without restart.

### Settings managed by environment variables

If a setting has a matching environment variable in your `.env` (or compose
file), the environment owns it: the deployment rewrites that value on every
container start. Those fields are shown read-only on the Settings page, labelled
*"Managed by `EMAIL_HOST` in the environment"*, so an edit you make in the UI
can't be silently reverted by the next restart.

| Setting | Environment variable |
|---------|----------------------|
| Organization Name | `ORGANIZATION_NAME` |
| Default Language | `ORGANIZATION_LANGUAGE` |
| Contact Email / From Email | `DEFAULT_FROM_EMAIL` |
| SMTP Host | `EMAIL_HOST` |
| SMTP Port | `EMAIL_PORT` |
| SMTP Username | `EMAIL_HOST_USER` |
| SMTP Password | `EMAIL_HOST_PASSWORD` |
| Use TLS | `EMAIL_USE_TLS` |

To manage a setting from the UI instead, leave its variable unset — or set it to
an empty value (`EMAIL_HOST=`), which hands the field back to the UI without
removing the line. Settings with no environment variable (anonymity threshold,
registration options) are always editable in the UI.

### Report Settings
- **Minimum Responses for Anonymity** - Minimum number of responses required to display results
  - Set to `1` for small teams where anonymity is less critical
  - Set to `3+` for larger teams to protect reviewer anonymity
  - Groups with fewer responses than the threshold are hidden in reports. A department with two staff members needs a threshold of 2, or the direct-report group is hidden for its head.
  - Self-assessments are always shown regardless of this setting. The manager group is also exempt from the threshold: the report shows it with one response.
- **Automatically send report email when generated** - Send the reviewee the report-ready email when the cycle completes
- **Attach the report as a PDF to the email** - Add the report PDF to the report-ready email. On by default.
- **Report PDF Retention (days)** - How long Blik keeps a stored report PDF. Leave it empty to use the default from `REPORT_PDF_RETENTION_DAYS` (30 days). After this period the PDF is deleted. The report page then shows **Regenerate PDF** instead of **Download PDF**. See [Report PDFs](#report-pdfs).

---

## Who Can See What

Blik has two roles inside an organization:

| | Organization Admin | Organization Member |
|---|---|---|
| Cycles list & detail | All cycles in the organization | Only cycles where they are the reviewee |
| Reports | All reports in the organization | Only their own |
| Organization settings, team, API tokens | Yes | No |

Feedback is anonymous to *everyone*, admins included: the system stores no link
between a reviewer's identity and their answers, and responses below the
anonymity threshold are hidden in reports (see [Report Settings](#report-settings)).

A member's own report reaches them through a private link containing an access
token. That link needs no login — treat it as a secret. It is shown to admins on
the cycle page and emailed to the reviewee when a cycle closes.

The same rules apply to the REST API (`/api/v1/cycles/`, `/api/v1/reports/`):
a token authenticates as the user who created it and sees exactly what that user
would see in the dashboard.

---

## Managing Reviewees

### Creating Reviewees

1. Navigate to **Dashboard → Reviewees → Create New**
2. Enter:
   - **Name** - Full name of the person being reviewed
   - **Email** - Email for notifications (self-assessment link, report ready)
   - **Department** (optional) - Organizational unit
   - **Position** (optional) - Job title
3. Click **Create Reviewee**

### Editing Reviewees

1. Navigate to **Dashboard → Reviewees**
2. Click **Edit** next to the reviewee
3. Update information and click **Save Changes**

### Deactivating Reviewees

1. Click **Delete** next to the reviewee
2. Confirm deletion
3. Reviewees are marked inactive rather than deleted (preserves historical data)

---

## Org Chart

The org chart records who is in which unit and who manages it. Blik uses it to suggest managers, peers and direct reports for a review cycle, and to fill the reviewers of bulk-created cycles. Open it at **Dashboard → Organization → Org chart**. Only users with the permission to manage the organization can edit it.

### How Units Work

- A **unit** is a department, a team or a professor's area. It has a name. Unit names are unique in an organization.
- A unit has a **manager row** and a **member row**. A person is in a unit once, as manager or as member.
- Units **stack**: when the manager of unit B is a member of unit A, the chart shows B under A. So one person can manage one unit and be a member of another.
- People who are in no unit are listed under **Not in a unit**.

### Editing the Chart

The page has two views. Use the **Chart** and **Outline** tabs to switch.

- **Chart** shows the units as boxes in a tree. Use **+**, **−** and **Fit to screen** to zoom. Drag the background to move around. Click **N units below** on a unit to collapse or expand the units under it.
- **Outline** shows the units as a list. Use **Expand all** and **Collapse all**. Drag a unit onto another unit to place it below that unit.

Actions:

1. Click **New unit** and enter a name.
2. Open the **⋯** menu of a unit for **Add manager**, **Add member**, **Rename**, **Place under another unit** and **Delete unit**.
   - **Add manager** and **Add member** open a picker. Find a person, or type a name and email to add someone new.
   - **Place under another unit** makes the manager of this unit a member of the unit above. Blik refuses this when the unit has no manager, when the target unit is below this unit in the tree, or when the manager already manages the target unit.
   - **Delete unit** keeps the people in Blik. People who are in no other unit move to **Not in a unit**.
3. Drag a person onto the manager row or the member row of a unit to move them there. Hold **Alt** (or **Ctrl**) while you drag to copy the person, so they stay in the first unit too. Drag a person from **Not in a unit** onto a unit to place them. Drag a person onto **Not in a unit**, or click **×** on the person, to take them out of a unit.

### Importing a CSV File

1. Click **Import CSV**, choose the file and click **Next**. The file must be a UTF-8 CSV file smaller than 1 MB. Comma, semicolon and tab separators work.
2. On the **Import CSV** page, check **Which column is which?**. Blik guesses the mapping from the column names. Correct a choice where needed. The first five rows of the file show which column goes to which field.
3. Click **Import**.

The file has one row per person. Give the email column and a name column, or a first-name column and a last-name column. The department column and the manager column are optional. The manager column holds the manager's email, or the manager's name as it is written in the file.

| Name | Email | Department | Manager |
|------|-------|------------|---------|
| Anna Berg | anna@example.com | Optics | |
| Tom Vos | tom@example.com | Optics | anna@example.com |
| Lea Kuhn | lea@example.com | Optics | Anna Berg |

Blik recognises common column names in English, German and Dutch, in any letter case: for example `Name`, `Vollständiger Name`, `Naam`; `First name`, `Vorname`, `Voornaam`; `Last name`, `Nachname`, `Achternaam`; `Email`, `E-Mail-Adresse`, `E-mailadres`; `Department`, `Team`, `Abteilung`, `Afdeling`; `Manager`, `Supervisor`, `Reports to`, `Vorgesetzter`, `Leidinggevende`. Other column names work too: map them by hand in step 2.

Each person who is named as a manager gets one unit. They are its manager. The people who report to them are its members. The unit is named after the manager's department, or after the manager when the department is empty. So a head of department is a member of the director's unit and the manager of their own unit.

Blik checks the file before it writes anything. It reports these errors with the line number: an invalid email, an email that is in the file twice, an empty name, a manager who is not in the file, a manager name that matches more than one person (use the email instead), and a person who is their own manager. Nothing is imported while there is an error.

**The import replaces the chart.** All current units are deleted and built again from the file. People who are not in the file stay in Blik as reviewees, but they are no longer in a unit. People in the file are matched by email: an existing reviewee gets the name and department from the file and is set active; a new reviewee is created. The reviewee limit of your plan applies to each new person.

### Who Reviews Whom

When Blik derives the reviewers of a person from the chart:

- **Managers** are the managers of every unit where the person is a member.
- **Direct reports** are the members of every unit where the person is a manager.
- **Peers** are the other members of every unit where the person is a member, and the other managers of every unit where the person is a manager.

When one person lands in more than one group, the first group in this order keeps them: self, manager, direct report, peer. Within a group the names are sorted alphabetically.

In single cycle creation, Blik fills the reviewer pickers from the chart when you select a reviewee who is in a unit. Blik shows a notice when the reviewee is not in the chart. You can change the lists before you create the cycle.

---

## Creating Review Cycles

A review cycle is a 360-degree feedback collection period for a reviewee.

### Single Cycle Creation

1. Navigate to **Dashboard → Review Cycles → Create New**
2. Select **Single Reviewee** mode
3. Choose:
   - **Reviewee** - Person being reviewed
   - **Questionnaire** - Feedback questionnaire to use
4. Configure token counts (can be set to 0 for dynamic creation):
   - **Self Assessment** - Usually 1
   - **Peer Reviews** - Number of colleague reviewers
   - **Manager Reviews** - Usually 1
   - **Direct Report Reviews** - Number of team members
5. Click **Create Review Cycle**

### Bulk Cycle Creation

Bulk creation makes one review cycle for every active reviewee. No email is sent until you confirm on the next page.

1. Select **Bulk Create** mode
2. Choose the questionnaire and the feedback categories
3. Under **Reviewers per cycle**, choose where the reviewers come from:
   - **Derive from org chart** - Blik fills the manager, peer and direct report reviewers of each reviewee from the [org chart](#org-chart), and adds the reviewee's own self-assessment. This option is available when the chart has at least one unit.
   - **Leave empty** - Blik creates the cycles without reviewers. You assign reviewers per cycle afterwards.
4. Click **Create Cycles (no emails yet)**

In chart mode, Blik skips a reviewee who gets no reviewers from the chart for the selected categories. No cycle is created for them and no cycle credit is used. The success message says how many cycles were created and how many reviewees were skipped.

Blik refuses the whole batch when your plan has fewer cycle credits than active reviewees.

### Sending the Bulk Invitations

After creation, Blik opens the **Send invitations** page. It lists the new cycles. In chart mode it shows per cycle how many self, manager, peer and direct report reviewers were found. Check the list. Edit a cycle afterwards if something is not correct.

Click **Send all invitations** to send, or **Skip — I'll send later** to send per cycle from the cycle pages later.

What is sent depends on where the reviewers came from:

- **Derive from org chart** - Every person gets **one email** with all the forms they have to fill in across all the new cycles, their own self-assessment included. The email lists each form with the name of the person it is about, the relation (manager, peer, direct report), the questionnaire and the estimated minutes, with a **Start the review** button per form. It also links to the [personal overview page](#the-personal-overview-page). No separate self-assessment email and no invitation links email are sent. A person with a single form gets the normal single invitation email instead (for a self-assessment, the self-assessment email).
- **Leave empty** - Every reviewee gets the two usual emails: the self-assessment email and the invitation links email with the category links to share. See [What Happens After Creation](#what-happens-after-creation).

The success message says how many review cycles the invitations cover, and in chart mode how many reviewer invitations go out in how many emails.

### What Happens After Creation

In single cycle creation, and in bulk creation with **Leave empty**, the reviewee receives two emails:
1. **Self-Assessment Email** - Personal link to complete their self-assessment
2. **Invitation Links Email** - Category links (peer/manager/direct report) to share with others

In bulk creation with **Derive from org chart**, these two emails are not sent. Every person gets one bundled email instead. See [Sending the Bulk Invitations](#sending-the-bulk-invitations).

---

## Managing Invitations

### Understanding the Invitation System

**Dynamic Token Creation:**
- You can create a cycle with 0 tokens for any category
- Each invitation link can be shared with multiple people
- Tokens are created automatically when someone clicks the link
- Once a token is claimed, it cannot be reused (prevents duplicate reviews)

### Invitation Links (Recommended Approach)

1. Navigate to **Dashboard → Review Cycles → [Cycle Name]**
2. In the **Invitation Links** section, copy the relevant links:
   - **Self Assessment** - For the reviewee
   - **Peer Review** - Share with colleagues
   - **Manager Review** - Share with manager(s)
   - **Direct Report Review** - Share with team members
3. Share links via email, Slack, or other channels

**How it works:**
- First person clicks link → Gets Token 1
- Second person clicks link → Gets Token 2 (or creates new token if none available)
- Each person's token is saved in their browser (localStorage) so they can return later

### Email-Based Invitations (Optional)

For more control over who receives invitations:

1. Click **Manage Invitations** on the cycle detail page
2. Enter email addresses for each category (comma or newline separated)
3. Click **Assign Emails to Tokens**
4. Emails are randomly shuffled and assigned to tokens (maintains anonymity)
5. Click **Send Pending Invitations** to email reviewers

### The Personal Overview Page

Every bundled invitation email links to a personal overview page. The page lists the forms the address was asked to fill in, in two groups: **About you** (the person's own self-assessments) and **About others**. It shows how many forms are done, about how many minutes the open forms take, and a **Start**, **Continue**, **Done** or **Closed** state per form. The link is a signed URL that carries the email address and the organization; Blik stores nothing for it. The link works for 30 days. After that, the page offers a button that sends a new link to the same address. Anyone with the link sees only which forms that address was asked to fill in, never answers or results.

### Sending Reminders

1. Navigate to the cycle detail page
2. Click **Send Reminders** (shows count of pending reviews)
3. Select which tokens to remind (or all)
4. Click **Send Reminder Emails**

---

## Closing Cycles & Generating Reports

### When to Close a Cycle

Close a cycle when:
- All expected reviews are completed
- You want to generate a report with partial responses
- The review period has ended

### Closing Process

1. Navigate to **Dashboard → Review Cycles → [Cycle Name]**
2. Click **Close Cycle & Generate Report**
3. System validates at least one review is completed
4. Cycle is marked as completed (no further reviews can be submitted)
5. Report is automatically generated and the report PDF is stored
6. Reviewee receives email notification with secure report link; the PDF is attached when **Attach the report as a PDF to the email** is on

You can close a cycle before the reviewee submits the self-assessment. The report then shows the results from the others without the self-assessment parts. See [Reports Without a Self-Assessment](REPORT_GUIDE.md#reports-without-a-self-assessment).

### Report PDFs

A cycle completes by itself when the last reviewer submits. The cron job `finalize_reports` runs every 5 minutes and finalises each completed cycle: it generates the report, stores the report PDF, and sends the report-ready email when **Automatically send report email when generated** is on. When **Attach the report as a PDF to the email** is on, the email carries the PDF. When the PDF build fails, the job tries again on its next runs. After three failed attempts it sends the email without the PDF. **Close Cycle & Generate Report** and **Regenerate Report** on the cycle page do the same at once and always send the email.

On the report page, **Download PDF** downloads the stored PDF. When no valid PDF is stored, the page shows **Regenerate PDF** instead. It builds a new PDF and downloads it. The reviewee's report page has the same buttons. The stored PDF is in the reviewee's language. An admin who views the report in another language gets a fresh render in that language.

A stored PDF is deleted after the retention period (**Report PDF Retention (days)**, default 30). The report itself stays. The cron job deletes expired PDFs on each run.

### Manual Report Generation

If you need to regenerate a report:

1. Click **Regenerate Report** on the cycle detail page
2. Report is rebuilt with current responses
3. New notification email is sent to reviewee

### Viewing Reports

**Staff View:**
- Click **View Report (Staff)** - Shows all responses including raw data

**Reviewee View:**
- Click **View Report (Reviewee)** - Reviewee's personalized report with insights
- Share this link with the reviewee (or they'll receive it via email)

---

## Questionnaire Management

### Default Questionnaire

The system includes a Dreyfus-model based questionnaire covering:
- Technical Expertise & Problem Solving
- Leadership & Initiative
- Collaboration & Communication
- Adaptability & Learning

### Viewing Questionnaires

1. Navigate to **Dashboard → Questionnaires**
2. Click **Preview** to see questions and structure
3. Shows sections, questions, and rating scales

### Custom Questionnaires

Custom questionnaires must be created via Django Admin:

1. Navigate to `/admin/questionnaires/questionnaire/`
2. Click **Add Questionnaire**
3. Create sections and add questions
4. Configure question types:
   - **Rating** - 1-5 scale with optional labels
   - **Text** - Open-ended feedback
   - **Multiple Choice** - Predefined options

---

## Best Practices

### Token Planning

- **Start with 0 tokens** - Let the invitation link dynamically create tokens as needed
- **Self-assessment**: Always create at least 1 token upfront
- **Peer reviews**: Use dynamic creation (set to 0 and share link)
- **Manager/Direct Reports**: Set exact count if known, or use dynamic creation

### Email Notifications

- **Test SMTP settings** before launching cycles (use setup wizard's test data)
- **Check spam folders** if reviewees report missing emails
- **Use clear from_email** (e.g., `feedback@company.com` not `noreply@localhost`)

### Anonymity & Privacy

- **Never check individual token responses** unless investigating issues
- **Set appropriate minimum response threshold** in settings
- **Remind reviewers** their individual responses are not shown to the reviewee
- **Self-assessments are always visible** in the report (clearly labeled)

### Timing

- **Allow 1-2 weeks** for review completion
- **Send reminder emails** after 3-5 days
- **Close cycles promptly** after deadline to generate reports
- **Bulk creation** is efficient for organization-wide review periods

### Communication

- **Explain the process** to reviewees before launching cycles
- **Provide context** on how feedback will be used
- **Set expectations** on report delivery timing
- **Follow up** with 1-on-1 discussions after report delivery

---

## Troubleshooting

### Emails Not Sending

1. Check **Settings → Email (SMTP) Settings**
2. Verify SMTP credentials are correct
3. Test with a single cycle first
4. Check email server logs or use Mailpit for development testing

### Missing Invitation Links

- Invitation links only appear for cycles with invitation tokens
- If missing, the cycle was created before the secure invitation system
- Create a new cycle or regenerate invitation tokens via Django Admin

### Report Generation Fails

- Ensure at least one review is completed
- Check that responses have proper data format (`{'value': ...}`)
- View error message in the admin dashboard
- Check application logs for detailed error trace

### Token Reuse Issues

- Tokens are claimed when first accessed
- If someone loses their link, they can find it in browser localStorage
- If localStorage is cleared, they'll get a new token (intended behavior)
- For critical situations, use email-based invitations to track specific reviewers

---

## Security Notes

### URL Security

All invitation and report URLs use secure UUIDs (not enumerable IDs):
- Report URLs: `/my-report/<uuid>/`
- Invitation URLs: `/feedback/invite/<uuid>/`
- Token URLs: `/feedback/<uuid>/`

These cannot be guessed or enumerated, protecting privacy and preventing unauthorized access.

### Access Control

- Admin dashboard requires staff user login
- Reviewee reports are accessible via secure token (no login required)
- Feedback forms are accessible via token (anonymous, no login)

### Data Privacy

- Individual reviewer responses are anonymous to the reviewee
- Aggregated data only shown when minimum response threshold is met
- Self-assessments are clearly labeled in reports
