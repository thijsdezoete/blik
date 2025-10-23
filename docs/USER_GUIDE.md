# User Guide

Guide for reviewees and reviewers participating in the 360-degree feedback process.

## Table of Contents

- [For Reviewees](#for-reviewees)
- [For Reviewers](#for-reviewers)
- [Technical Details](#technical-details)
- [Privacy & Anonymity](#privacy--anonymity)
- [Frequently Asked Questions](#frequently-asked-questions)

---

## For Reviewees

You are receiving 360-degree feedback from your peers, manager, and direct reports to support your professional development.

### What to Expect

When a feedback cycle is created for you, you'll receive **two emails**:

1. **Self-Assessment Email**
   - Contains your personal link to complete a self-reflection
   - This is your opportunity to assess your own performance
   - Your self-assessment will be clearly labeled in the final report

2. **Invitation Links Email**
   - Contains links to share with others:
     - **Peer Review Link** - Share with colleagues
     - **Manager Review Link** - Share with your manager
     - **Direct Report Link** - Share with your team members
   - Each link can be shared with multiple people
   - You choose who receives these links

### Completing Your Self-Assessment

1. Click the link in your **Self-Assessment Email**
2. Answer all required questions honestly
3. Questions are based on the Dreyfus skill development model:
   - Technical expertise and problem-solving
   - Leadership and initiative
   - Collaboration and communication
   - Adaptability and learning
4. You can save progress and return later (link is bookmarked in your browser)
5. Click **Submit Feedback** when complete

**Important:**
- Your self-assessment is included in your final report (clearly marked)
- Be honest and reflective - this is for your development
- There are no "wrong" answers - the goal is growth

### Sharing Invitation Links

**Who should you ask for feedback?**

- **Peers** (3-5 people) - Colleagues who work with you regularly
- **Manager** (1-2 people) - Your direct manager or supervisor
- **Direct Reports** (if applicable) - Team members you manage

**How to share:**

1. Copy the relevant link from your **Invitation Links Email**
2. Send via email, Slack, or direct message
3. Include context: "I'm participating in a 360 review and would appreciate your honest feedback"
4. Set a deadline (usually 1-2 weeks)

**Tips:**
- Choose people who have worked with you in the past 6-12 months
- Select a diverse group with different perspectives
- Don't pressure anyone - participation should be voluntary
- Remind reviewers that responses are anonymous

### Receiving Your Report

When all reviews are completed (or the cycle is closed):

1. You'll receive an email: **"Your 360 Feedback Report is Ready!"**
2. Click the secure link to view your personalized report
3. The report includes:
   - Overall performance insights
   - Strength areas
   - Development opportunities
   - Perception gap analysis (if applicable)
   - Detailed feedback by competency area

**Understanding your report** - See the [Report Interpretation Guide](REPORT_GUIDE.md)

### After Receiving Your Report

1. **Review carefully** - Take time to read and reflect
2. **Look for patterns** - What themes emerge across multiple reviewers?
3. **Identify surprises** - Are there perception gaps (how you see yourself vs. how others see you)?
4. **Create an action plan** - Focus on 1-3 key development areas
5. **Discuss with your manager** - Schedule a follow-up conversation
6. **Track progress** - Future review cycles will show your growth

---

## For Reviewers

You've been asked to provide feedback for a colleague. Your honest, constructive input is valuable for their development.

### What You'll Receive

You'll receive either:
- **An invitation link** shared directly from the reviewee
- **An email invitation** from the system (if email-based invitations are used)

### Providing Feedback

1. **Click the invitation link** you received
2. You'll see a multi-step form with sections:
   - Technical Expertise & Problem Solving
   - Leadership & Initiative
   - Collaboration & Communication
   - Adaptability & Learning
3. **Answer questions using:**
   - **Rating scales** (1-5) - Be honest, use the full scale
   - **Open-text responses** - Provide specific examples when possible
4. **Save and return** - Your progress is saved automatically
   - Your browser remembers your feedback link
   - You can close and return later
5. **Submit** when complete

### Writing Effective Feedback

**Do:**
- Be specific and provide examples
- Focus on behaviors, not personality
- Balance strengths and development areas
- Be constructive - suggest how they might improve
- Consider their role and responsibilities

**Don't:**
- Make personal attacks or harsh judgments
- Reference specific incidents that reveal your identity
- Exaggerate or dramatize issues
- Leave all fields blank or give all 5s without thought

**Example Good Feedback:**
- ❌ "Communication is bad"
- ✅ "Sometimes explanations could be clearer. For example, breaking down technical concepts for non-technical stakeholders would help team alignment."

### Rating Scale Guide

Most questions use a 1-5 scale:

- **5 - Expert/Exceptional** - Consistently exceeds expectations, recognized leader in this area
- **4 - Proficient/Strong** - Regularly meets and often exceeds expectations
- **3 - Competent/Solid** - Consistently meets expectations
- **2 - Advanced Beginner** - Developing, sometimes meets expectations with support
- **1 - Novice/Needs Development** - Requires significant development in this area

**Tips:**
- Use the full scale - not everyone should be 4-5
- Compare to others in similar roles, not to experts in the field
- Consider frequency: "sometimes" vs "consistently"

### Time Commitment

- **10-15 minutes** for most questionnaires
- Can be completed in multiple sessions
- Worth the investment for meaningful feedback

---

## Technical Details

### How the System Works

**Invitation Links:**
- Each category (peer/manager/direct report) has a unique secure link
- When you click a link, you're assigned a random anonymous token
- Your token is saved in your browser (localStorage)
- You can bookmark or return to the same link

**Anonymous Tokens:**
- Each reviewer gets a unique, random token
- Tokens are not linked to your identity
- Multiple people can use the same invitation link
- Each gets their own unique token

**Progress Saving:**
- Answers are saved when you click "Next" or "Submit"
- Browser remembers your token for easy return
- If you lose the link, your browser can retrieve it (via localStorage)

### Browser Requirements

- Modern browser (Chrome, Firefox, Safari, Edge)
- JavaScript enabled (for progress saving and multi-step form)
- Cookies/localStorage enabled (to remember your token)

### Troubleshooting

**"I lost my feedback link"**
- Return to the original invitation link you clicked
- Your browser will recognize you and redirect to your saved progress

**"My progress wasn't saved"**
- Ensure JavaScript is enabled
- Click "Next" between sections (don't just close the browser)
- Use the same browser/device you started on

**"I accidentally submitted incomplete feedback"**
- Contact the administrator who can view submission status
- In some cases, feedback can be reopened

**"I can't access the link"**
- Check if the cycle has been closed
- Verify the link wasn't truncated in your email
- Try a different browser
- Contact the system administrator

---

## Privacy & Anonymity

### For Reviewees

**What you'll see in your report:**
- Aggregated ratings by category (Self, Peer, Manager, Direct Report)
- Anonymous text feedback (no names attached)
- Your own self-assessment (clearly labeled)

**What you won't see:**
- Individual reviewer names or identities
- Which specific person gave which rating
- Individual responses if below the anonymity threshold

**Anonymity Protection:**
- Minimum response threshold (usually 3) for each category
- If fewer responses, data may be hidden or combined
- Self-assessments always shown (you know it's yours)

### For Reviewers

**Your responses are anonymous:**
- Your name is never stored with your feedback
- Reviewee sees aggregated data only
- System uses random tokens, not user accounts

**However:**
- Very specific details in text responses might reveal your identity
- If you're the only manager or direct report, category might reveal you
- Administrator can technically view individual responses (but shouldn't)

**Best practice:**
- Write feedback you'd be comfortable sharing face-to-face
- Focus on behaviors and patterns, not one-off incidents
- Avoid overly specific details that identify you

---

## Frequently Asked Questions

### For Reviewees

**Q: How do I know who to ask for feedback?**
A: Choose people who have worked closely with you in the past 6-12 months. Aim for 3-5 peers, your manager, and any direct reports. Diversity of perspective is valuable.

**Q: What if someone doesn't complete their feedback?**
A: The system allows partial reporting. Your cycle can be closed once you have enough responses for meaningful insights (usually 1-2 per category minimum).

**Q: Can I see who hasn't completed their feedback?**
A: No, to preserve anonymity. You can ask your administrator to send reminders to pending reviewers.

**Q: What if I disagree with my report?**
A: Perception gaps are common and valuable learning opportunities. Discuss with your manager to understand different perspectives and create a development plan.

**Q: How often should I do 360 reviews?**
A: Typically annually or bi-annually. This allows time to work on development areas and measure progress.

### For Reviewers

**Q: Will the reviewee know I gave low ratings?**
A: No, your responses are anonymous and aggregated. They'll see average ratings by category, not individual responses.

**Q: What if I don't feel qualified to rate someone on a topic?**
A: Rate based on your observations and interactions. It's okay to give middle scores (3) if you haven't observed exceptional or poor performance in that area.

**Q: Can I skip questions?**
A: Required questions must be answered. Optional questions can be skipped if you don't have relevant input.

**Q: How honest should I be?**
A: Be constructive but truthful. The goal is development, not criticism. Frame feedback in terms of growth opportunities.

**Q: What if I started feedback but want to restart?**
A: Your progress is auto-saved. Clicking "Previous" lets you review earlier answers. If you need to fully restart, contact the administrator.

---

## Getting Help

**Technical Issues:**
- Contact your system administrator
- Include the cycle name or reviewee name
- Describe what's not working

**Process Questions:**
- Ask your HR team or whoever initiated the review
- Refer to this guide and the [Report Interpretation Guide](REPORT_GUIDE.md)

**Privacy Concerns:**
- Discuss with your manager or HR
- System administrator can explain data handling procedures
