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
