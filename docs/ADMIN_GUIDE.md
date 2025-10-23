# Admin Guide

Complete guide for administrators setting up and managing the 360 feedback system.

## Table of Contents

- [Initial Setup](#initial-setup)
- [Organization Settings](#organization-settings)
- [Managing Reviewees](#managing-reviewees)
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

### Report Settings
- **Minimum Responses for Anonymity** - Minimum number of responses required to display results
  - Set to `1` for small teams where anonymity is less critical
  - Set to `3+` for larger teams to protect reviewer anonymity
  - Self-assessments are always shown regardless of this setting

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

1. Select **Bulk Creation** mode
2. Choose questionnaire
3. Set token counts (applies to all reviewees)
4. Click **Create Review Cycles**
5. Creates one cycle for each active reviewee

### What Happens After Creation

The reviewee automatically receives two emails:
1. **Self-Assessment Email** - Personal link to complete their self-assessment
2. **Invitation Links Email** - Category links (peer/manager/direct report) to share with others

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
5. Report is automatically generated
6. Reviewee receives email notification with secure report link

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
