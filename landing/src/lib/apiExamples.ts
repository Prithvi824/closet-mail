/** Example "create an alias" calls shown in the API section, split into coloured segments. */

import { SITE } from "./site";

export type Tone = "plain" | "dim" | "key" | "string" | "field";
export type Segment = readonly [Tone, string];

export interface CodeSample {
  id: string;
  label: string;
  segments: readonly Segment[];
}

const endpoint = `${SITE.appUrl}/api/v1/aliases`;
const example = `maple.otter17@${SITE.domain}`;

export const API_SAMPLES: readonly CodeSample[] = [
  {
    id: "curl",
    label: "curl",
    segments: [
      ["key", "curl"],
      ["plain", ` -X POST ${endpoint} \\\n  -H `],
      ["string", '"Authorization: Bearer ma_3fk2…"'],
      ["plain", " \\\n  -d "],
      ["string", `'{"format": "words", "description": "Bakery"}'`],
      ["plain", "\n\n"],
      ["dim", "# 201 Created"],
      ["plain", "\n{\n  "],
      ["field", '"address"'],
      ["plain", ": "],
      ["string", `"${example}"`],
      ["plain", ",\n  "],
      ["field", '"state"'],
      ["plain", ": "],
      ["string", '"active"'],
      ["plain", ",\n  "],
      ["field", '"reply_enabled"'],
      ["plain", ": "],
      ["key", "true"],
      ["plain", "\n}"],
    ],
  },
  {
    id: "js",
    label: "JavaScript",
    segments: [
      ["key", "const"],
      ["plain", " res = "],
      ["key", "await"],
      ["plain", " fetch("],
      ["string", `"${endpoint}"`],
      ["plain", ", {\n  method: "],
      ["string", '"POST"'],
      ["plain", ",\n  headers: { Authorization: "],
      ["string", "`Bearer ${token}`"],
      ["plain", " },\n  body: JSON.stringify({ format: "],
      ["string", '"words"'],
      ["plain", ", description: "],
      ["string", '"Bakery"'],
      ["plain", " }),\n});\n"],
      ["key", "const"],
      ["plain", " { address } = "],
      ["key", "await"],
      ["plain", " res.json();\n"],
      ["dim", `// "${example}"`],
    ],
  },
  {
    id: "py",
    label: "Python",
    segments: [
      ["key", "import"],
      ["plain", " httpx\n\nres = httpx.post(\n    "],
      ["string", `"${endpoint}"`],
      ["plain", ",\n    headers={"],
      ["string", '"Authorization"'],
      ["plain", ": "],
      ["string", 'f"Bearer {token}"'],
      ["plain", "},\n    json={"],
      ["string", '"format"'],
      ["plain", ": "],
      ["string", '"words"'],
      ["plain", ", "],
      ["string", '"description"'],
      ["plain", ": "],
      ["string", '"Bakery"'],
      ["plain", "},\n)\n"],
      ["key", "print"],
      ["plain", "(res.json()["],
      ["string", '"address"'],
      ["plain", "])  "],
      ["dim", `# ${example}`],
    ],
  },
];
