const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The value if it is a UUID, else undefined.
 *
 * Route and query parameters are interpolated into API paths. React Router decodes `%2F`
 * in params, so a crafted link such as `/projects/..%2Forg%2F<id>%2Fapi-keys%3F` used to make
 * an authenticated request to an arbitrary same-origin API path. Every id in this app is a
 * UUID, so anything else is treated as "not found".
 */
export function asUuid(value: string | null | undefined): string | undefined {
  return value && UUID.test(value) ? value : undefined;
}
