// CloudFront viewer-request function for the web behaviour (not /api/*). Which file a path gets:
//
//   /                      the Kartaa landing page for a visitor, the app's index.html for someone signed in
//                          (the app sets the plain `kartaa_in=1` hint cookie while a session is live;
//                          web/src/auth/session.ts). The hint only picks a static page; no authorization
//                          depends on it, and the app checks the real session itself.
//   /styles.css, /fonts/*  the landing page's own files, kept under _landing/ in the bucket
//   /signin, /signup, /b/...  any path whose last segment has no dot is an app route: index.html
//   anything else          the file of that name (hashed /assets/*, favicon.svg)
//
// The function runs before the cache lookup, so the cache key is the rewritten path: the two pages never
// share a cache entry even though the cache policy ignores cookies. Test: node infra/modules/cdn/routing.test.mjs
function handler(event) {
  var request = event.request;
  var uri = request.uri;
  if (uri === '/' || uri === '/index.html') {
    var hint = request.cookies && request.cookies['kartaa_in'];
    request.uri = hint && hint.value === '1' ? '/index.html' : '/_landing/index.html';
  } else if (uri === '/styles.css' || uri.indexOf('/fonts/') === 0) {
    request.uri = '/_landing' + uri;
  } else if (uri.split('/').pop().indexOf('.') === -1) {
    request.uri = '/index.html';
  }
  return request;
}
