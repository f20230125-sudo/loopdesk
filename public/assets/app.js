// Progressive enhancement: every command and relationship check also runs on the server.
const organisation = document.querySelector('#opportunity-organisation');
const contact = document.querySelector('#opportunity-contact');
if (organisation && contact) {
  const options = Array.from(contact.options).slice(1).map(option => option.cloneNode(true));
  function syncContacts() {
    const selected = contact.value;
    contact.replaceChildren(new Option('Choose a contact', ''));
    for (const option of options) {
      if (option.dataset.organisation === organisation.value) {
        const copy = option.cloneNode(true);
        copy.selected = copy.value === selected;
        contact.append(copy);
      }
    }
  }
  organisation.addEventListener('change', syncContacts);
  syncContacts();
}

const pairCode = document.querySelector('#pair-code');
const copyCode = document.querySelector('#copy-pair-code');
const copyStatus = document.querySelector('#copy-code-status');
if (pairCode && copyCode && copyStatus) {
  copyCode.hidden = false;
  copyCode.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(pairCode.value);
      copyStatus.textContent = 'Code copied. Paste it into the FollowDesk tab.';
    } catch {
      pairCode.focus();
      pairCode.select();
      copyStatus.textContent = 'Code selected. Copy it with your keyboard or device menu.';
    }
  });
}
