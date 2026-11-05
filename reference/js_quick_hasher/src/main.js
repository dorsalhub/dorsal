#!/usr/bin/env node
// Copyright 2025-2026 Dorsal Hub LTD
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import { parseArgs } from "node:util";

import { QuickHasher } from "./quick_hasher.js";

const USAGE = "Usage: js_quick_hasher [--predictable-bin <path>] <file>";

let parsed;
try {
  parsed = parseArgs({
    allowPositionals: true,
    options: { "predictable-bin": { type: "string" } },
  });
} catch (error) {
  console.error(`${error.message}\n${USAGE}`);
  process.exit(2);
}

if (parsed.positionals.length !== 1) {
  console.error(USAGE);
  process.exit(2);
}

try {
  const hasher = new QuickHasher({ predictableBinPath: parsed.values["predictable-bin"] });
  console.log(await hasher.hash(parsed.positionals[0]));
} catch (error) {
  console.error(`Error generating quick hash: ${error.message}`);
  process.exit(1);
}
