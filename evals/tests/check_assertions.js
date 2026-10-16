// Checks the text assertions of every Promptfoo scenario with JavaScript regex semantics
// (Promptfoo evaluates `regex` as `new RegExp(value)`). Good outputs must pass all text
// assertions; bad outputs must fail at least one. Exit code 1 on any mismatch.
'use strict';

const fs = require('fs');
const path = require('path');

const evalsDir = path.resolve(__dirname, '..');
const yaml = require(path.join(evalsDir, '..', 'node_modules', 'js-yaml'));

const load = (file) => yaml.load(fs.readFileSync(path.join(evalsDir, file), 'utf8'));
const scenarios = [...load('faq_scenarios.yaml'), ...load('appointment_scenarios.yaml')];
const cases = load(path.join('tests', 'assertion_cases.yaml'));

const TEXT_TYPES = new Set(['regex', 'not-regex', 'contains', 'not-contains', 'icontains', 'not-icontains']);

function check(assertion, output) {
  const inverse = assertion.type.startsWith('not-');
  const base = inverse ? assertion.type.slice(4) : assertion.type;
  let pass;
  if (base === 'regex') pass = new RegExp(assertion.value).test(output);
  else if (base === 'contains') pass = output.includes(String(assertion.value));
  else if (base === 'icontains') pass = output.toLowerCase().includes(String(assertion.value).toLowerCase());
  else throw new Error(`unsupported assertion type ${assertion.type}`);
  return pass !== inverse;
}

let failures = 0;
let checked = 0;
const fail = (message) => { failures += 1; console.error(`FAIL ${message}`); };

for (const test of scenarios) {
  const name = test.vars.scenario;
  const textAssertions = (test.assert || []).filter((a) => TEXT_TYPES.has(a.type));
  for (const assertion of textAssertions) new RegExp(assertion.type.endsWith('regex') ? assertion.value : '');
  if (textAssertions.length === 0) continue;
  const scenarioCases = cases[name];
  if (!scenarioCases || !(scenarioCases.good || []).length || !(scenarioCases.bad || []).length) {
    fail(`${name}: needs at least one good and one bad output in assertion_cases.yaml`);
    continue;
  }
  for (const output of scenarioCases.good) {
    checked += 1;
    textAssertions.forEach((assertion, index) => {
      if (!check(assertion, output)) fail(`${name}: good output rejected by assertion #${index} (${assertion.type}): ${JSON.stringify(output)}`);
    });
  }
  for (const output of scenarioCases.bad) {
    checked += 1;
    if (textAssertions.every((assertion) => check(assertion, output))) {
      fail(`${name}: bad output accepted: ${JSON.stringify(output)}`);
    }
  }
}
for (const name of Object.keys(cases)) {
  if (!scenarios.some((test) => test.vars.scenario === name)) fail(`${name}: case file refers to an unknown scenario`);
}

console.log(`${checked} outputs checked against ${scenarios.length} scenarios; ${failures} failure(s).`);
process.exit(failures ? 1 : 0);
