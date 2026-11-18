/** Builds the pre-filled "get in touch" email that the landing page's contact buttons open. */

import { SITE } from "./site";

export const CONTACT_SUBJECT = "closet-mail: request a subdomain";

/**
 * The fields a visitor fills in. The operator creates their subdomain and emails the inbox they
 * name a verification link; that inbox then receives their mail.
 */
export const CONTACT_BODY = [
  "Hi,",
  "",
  "I'd like my own closet-mail subdomain.",
  "",
  "Name:",
  `Label I'd like (it becomes <label>.${SITE.domain}):`,
  "Inbox where my mail should go (leave blank to use this address):",
  "Where you found closet-mail (LinkedIn, my resume, GitHub, a friend):",
  "",
  "Thanks!",
].join("\n");

/**
 * Build a mailto: link with the subject and body already filled in.
 *
 * Args:
 *   to: Recipient address; defaults to the site's contact address.
 * Returns:
 *   The mailto: URL, with subject and body percent-encoded (RFC 6068).
 */
export function contactMailto(to: string = SITE.contactEmail): string {
  const query = `subject=${encodeURIComponent(CONTACT_SUBJECT)}&body=${encodeURIComponent(CONTACT_BODY)}`;
  return `mailto:${to}?${query}`;
}
