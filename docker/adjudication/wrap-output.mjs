import fs from "node:fs";

const MODEL_OUTPUT = "/output/model-output.json";
const METADATA = "/input/pass-metadata.json";
const FINAL_OUTPUT = "/output/adjudication.json";

function fail(message) {
  process.stderr.write(`invalid adjudication model output: ${message}\n`);
  process.exit(65);
}

function readJson(path) {
  try {
    return JSON.parse(fs.readFileSync(path, "utf8"));
  } catch (error) {
    fail(`${path}: ${error.message}`);
  }
}

function sameSet(left, right) {
  if (left.size !== right.size) return false;
  for (const value of left) if (!right.has(value)) return false;
  return true;
}

function validateLabel(decisionId, value) {
  if (decisionId === "routing.task_class") {
    const allowed = new Set([
      "implementation",
      "diagnosis",
      "review",
      "documentation",
      "other",
    ]);
    if (typeof value !== "string" || !allowed.has(value)) {
      fail(`invalid routing.task_class label: ${JSON.stringify(value)}`);
    }
    return;
  }
  if (decisionId === "routing.interaction_required") {
    if (typeof value !== "boolean") {
      fail(`invalid routing.interaction_required label: ${JSON.stringify(value)}`);
    }
    return;
  }
  if (decisionId === "routing.semantic_risk") {
    if (!Number.isInteger(value) || value < 0 || value > 2) {
      fail(`invalid routing.semantic_risk label: ${JSON.stringify(value)}`);
    }
    return;
  }
  fail(`unknown decision seam: ${decisionId}`);
}

const output = readJson(MODEL_OUTPUT);
const metadata = readJson(METADATA);

if (!output || typeof output !== "object" || Array.isArray(output)) {
  fail("top-level result must be an object");
}
if (!Array.isArray(output.records)) {
  fail("records must be an array");
}

const byCase = new Map();
for (const record of output.records) {
  if (!record || typeof record !== "object" || Array.isArray(record)) {
    fail("every record must be an object");
  }
  if (typeof record.case_id !== "string" || !record.case_id) {
    fail("every record needs a non-empty case_id");
  }
  if (byCase.has(record.case_id)) {
    fail(`duplicate case_id: ${record.case_id}`);
  }
  if (!record.labels || typeof record.labels !== "object" || Array.isArray(record.labels)) {
    fail(`labels must be an object for ${record.case_id}`);
  }
  byCase.set(record.case_id, record);
}

const expectedIds = metadata.expected_records.map((item) => item.case_id);
if (!sameSet(new Set(expectedIds), new Set(byCase.keys()))) {
  fail("case set does not exactly match the blinded adjudication view");
}

const finalRecords = [];
for (const expected of metadata.expected_records) {
  const record = byCase.get(expected.case_id);
  const actualDecisionIds = new Set(Object.keys(record.labels));
  const expectedDecisionIds = new Set(expected.decision_ids);
  if (!sameSet(actualDecisionIds, expectedDecisionIds)) {
    fail(
      `decision seam set mismatch for ${expected.case_id}; expected ` +
      `${JSON.stringify(expected.decision_ids)}, got ` +
      `${JSON.stringify(Object.keys(record.labels))}`
    );
  }
  const labels = {};
  for (const decisionId of expected.decision_ids) {
    const value = record.labels[decisionId];
    validateLabel(decisionId, value);
    labels[decisionId] = value;
  }
  finalRecords.push({ case_id: expected.case_id, labels });
}

const adjudication = {
  schema: "agent-workflow-benchmark/decision-study-adjudication-pass/v1",
  study_id: metadata.study_id,
  dataset_version: metadata.dataset_version,
  protocol_version: metadata.protocol_version,
  input_view_sha256: metadata.input_view_sha256,
  adjudicator_id: metadata.adjudicator_id,
  completed_at: new Date().toISOString(),
  attestation: {
    independent: true,
    treatment_outputs_seen: false,
    other_adjudicator_labels_seen: false,
  },
  records: finalRecords,
};

fs.writeFileSync(FINAL_OUTPUT, JSON.stringify(adjudication, null, 2) + "\n", {
  mode: 0o600,
});
