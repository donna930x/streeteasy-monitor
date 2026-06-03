/**
 * StreetEasy monitor — Google Sheets webhook.
 *
 * Deploy this as a Web App (Deploy ▸ New deployment ▸ Web app):
 *   - Execute as: Me
 *   - Who has access: Anyone   (the shared SECRET below is what protects it)
 * Copy the /exec URL into the monitor's SHEETS_WEBHOOK_URL env var, and set
 * the same secret string in SHEETS_WEBHOOK_SECRET.
 *
 * The Python side POSTs JSON:
 *   { secret, fields: [...col keys...], listings: [ {col: value, ...}, ... ] }
 *
 * This script:
 *   - rejects the request if the secret doesn't match
 *   - writes a header row once (Date Added + pretty column names + a clickable
 *     Listing column; listing_id is kept in a trailing column as the dedup key)
 *   - skips any listing whose listing_id already exists in the sheet
 *   - appends new rows with today's date and a =HYPERLINK() clickable link
 *   - returns { ok, added, total }
 */

// ⚠️ Must match SHEETS_WEBHOOK_SECRET on the Python side. Change this.
var SECRET = 'CHANGE_ME_TO_A_LONG_RANDOM_STRING';

// Pretty header labels per incoming field key. Order is taken from the
// `fields` array the client sends; anything not listed falls back to the key.
var LABELS = {
  address: 'Address',
  neighborhood: 'Neighborhood',
  price: 'Price',
  beds: 'Beds',
  baths: 'Baths',
  laundry: 'Laundry',
  elevator: 'Elevator',
  doorman: 'Doorman',
  date_available: 'Available',
  days_listed: 'Days on Market',
  contact_first: 'Contact First',
  contact_last: 'Contact Last',
  contact_company: 'Contact Company',
  contact_phone: 'Contact Phone',
  url: 'Listing',          // rendered as a clickable HYPERLINK
  message: 'Message',      // copy-paste viewing request
  listing_id: 'Listing ID' // dedup key, kept last
};

function doPost(e) {
  var lock = LockService.getScriptLock();
  lock.waitLock(30000); // serialize concurrent runs so dedup is race-free
  try {
    var body = JSON.parse(e.postData.contents);

    if (body.secret !== SECRET) {
      return _json({ ok: false, error: 'bad secret' });
    }

    var fields = body.fields || [];
    var listings = body.listings || [];
    if (!fields.length) {
      return _json({ ok: false, error: 'no fields' });
    }

    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];

    // --- header: self-healing -------------------------------------------
    // Expected header is derived from the fields the client sends. If the
    // sheet is empty OR its current header doesn't match (columns were added
    // / reordered), wipe it and rewrite. This prevents stale-header column
    // misalignment (e.g. a date bleeding into the Price column) without the
    // user ever having to clear the sheet by hand.
    var expected = ['Date Added'].concat(
      fields.map(function (f) { return LABELS[f] || f; })
    );

    var needsReset = true;
    if (sheet.getLastRow() >= 1) {
      var cur = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
      needsReset = (cur.length !== expected.length);
      for (var h = 0; !needsReset && h < expected.length; h++) {
        if (String(cur[h]) !== String(expected[h])) needsReset = true;
      }
    }
    if (needsReset) {
      sheet.clear();                       // clears contents AND formats
      sheet.appendRow(expected);
      sheet.getRange(1, 1, 1, expected.length).setFontWeight('bold');
      sheet.setFrozenRows(1);
    }

    // --- existing listing_ids (last column = listing_id) ---
    var idCol = fields.indexOf('listing_id'); // 0-based within fields
    var seen = {};
    var lastRow = sheet.getLastRow();
    if (idCol !== -1 && lastRow > 1) {
      // +1 to skip the leading Date Added column, +1 for 1-based sheet cols
      var sheetIdCol = idCol + 2;
      var ids = sheet.getRange(2, sheetIdCol, lastRow - 1, 1).getValues();
      for (var i = 0; i < ids.length; i++) {
        seen[String(ids[i][0])] = true;
      }
    }

    var today = Utilities.formatDate(
      new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd'
    );

    var added = 0;
    for (var j = 0; j < listings.length; j++) {
      var item = listings[j];
      var id = String(item.listing_id || item.url || '');
      if (!id || seen[id]) continue;
      seen[id] = true;

      var row = [today];
      for (var k = 0; k < fields.length; k++) {
        var key = fields[k];
        var val = item[key];
        if (key === 'url' && val) {
          // Clickable link; label it "View" so the cell isn't a giant URL.
          val = '=HYPERLINK("' + String(val).replace(/"/g, '""') + '","View")';
        }
        row.push(val === undefined || val === null ? '' : val);
      }
      sheet.appendRow(row);
      added++;
    }

    return _json({ ok: true, added: added, total: sheet.getLastRow() - 1 });
  } catch (err) {
    return _json({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
