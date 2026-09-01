# Google Form event submissions

This setup keeps submissions moderated. The private response sheet contains contact details; only a separate approved-event tab is published as CSV.

## 1. Create the form

Create a blank Google Form named **Submit a Music Mile Event**. Add these questions in this exact order:

1. **Event name** — Short answer, required
2. **Venue** — Short answer, required
3. **Start date** — Date, required
4. **Start time** — Time, required
5. **End date** — Date, optional
6. **End time** — Time, optional
7. **Event or ticket URL** — Short answer, required
8. **Description** — Paragraph, optional
9. **Submitter email** — Short answer, required
10. **Acknowledgement** — Checkbox, required; option: `I confirm this information is public and accurate.`

Do not enable Google's automatic email collection; the manual email question keeps the spreadsheet columns predictable. Set the confirmation message to: `Thanks! Your event will appear after it has been reviewed and approved.` Publish the form for anyone with the link, then copy its responder URL.

## 2. Link responses to Sheets

In the form, open **Responses**, choose **Link to Sheets**, and create a new spreadsheet. Google documents this flow at https://support.google.com/docs/answer/2917686.

In the resulting **Form Responses 1** sheet, put these two headings after the form-created columns:

- Cell L1: `Approved`
- Cell M1: `Admin notes`

For an accepted submission, enter `Yes` in its Approved cell.

## 3. Create a public, approved-only export

Add a new sheet tab named **Calendar Export**. In cell A1, paste:

```
=QUERY('Form Responses 1'!A:L,"select B,C,D,E,F,G,H,I where L = 'Yes' label B 'Event name', C 'Venue', D 'Start date', E 'Start time', F 'End date', G 'End time', H 'Event URL', I 'Description'",1)
```

This excludes submitter emails and unapproved rows. If your response tab has a different name or your Approved column is not L, adjust the formula accordingly.

Choose **File → Share → Publish to web**, select only **Calendar Export**, choose **Comma-separated values (.csv)**, publish it, and copy the CSV URL. Anyone with that URL can see the approved event fields, so never include private data in Calendar Export.

## 4. Configure the project

Edit `config/submissions.yml`:

```yaml
csv_url: "PASTE_PUBLISHED_CSV_URL_HERE"
form_url: "PASTE_GOOGLE_FORM_RESPONDER_URL_HERE"
```

Edit `docs/settings.js`:

```javascript
window.CALENDAR_SETTINGS = {
  submissionFormUrl: "PASTE_GOOGLE_FORM_RESPONDER_URL_HERE"
};
```

Commit the changes and manually run **Actions → Update calendar → Run workflow**. The log should show `OK Community submissions: N`.

## 5. Approve future events

Review new rows in Form Responses 1. Enter `Yes` under Approved only after checking the venue, dates, event URL, and description. Then run the workflow manually or wait for its next scheduled run. Duplicate submitted events with the same venue, title, and start time are automatically collapsed.
