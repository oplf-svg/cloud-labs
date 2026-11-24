// Every request comes through here first. Only the addresses of this site go on to the cache and the storage. Every other
// address turns into one that does not exist, so whoever makes up a million of them makes the storage answer once.
const addresses = [/* addresses */];

function handler(event) {
  const request = event.request;
  const asked = request.uri;

  if (addresses.includes(asked)) {
    request.uri = asked.endsWith('/') ? asked + 'index.html' : asked;
    return request;
  }
  if (addresses.includes(asked + '/')) return moved(asked + '/');
  if (asked.endsWith('/index.html')) {
    const folder = asked.slice(0, -'index.html'.length);
    if (addresses.includes(folder)) return moved(folder);
  }
  request.uri = '/-';
  return request;
}

function moved(address) {
  return { statusCode: 301, statusDescription: 'Moved Permanently', headers: { location: { value: address } } };
}
