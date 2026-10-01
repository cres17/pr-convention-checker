import type { DesktopEvent } from "./events";
import { decodeDesktopEvent } from "./eventSchema";

export type Group = { name: string; required?: string[]; evidence?: string };
export type Decision = {
  rule_id: string;
  status: string;
  reason: string;
  severity?: string;
  trigger_files: string[];
  unsatisfied_groups: Group[];
  satisfied_groups: Group[];
};
export type Violation = {
  rule_id: string;
  severity: string;
  confidence: string;
  message: string;
  checklist: string[];
  missing_docs_explanation: string;
  changed_contract_summary: string;
  docs_update_draft: string;
  false_positive_note: string;
};
export type PolicyPreview = {
  repository: string;
  exists: boolean;
  preset: string;
  presets: string[];
  recommendations: { presets: string[]; frameworks: string[]; docs_paths: string[] };
  policy: string;
};
export type ScanImpact = {
  scan_at: string;
  version: number;
  items: { id: string; title: string; path: string; line?: number; change: string; invalidated: boolean }[];
  documents: { path: string; invalidated: boolean; kind?: DocumentKind }[];
};
export type Scan = {
  repository: string;
  base: string;
  at: string;
  changed_file_count: number;
  policy: string;
  files: { path: string; patch: string; status: string }[];
  result: {
    result: string;
    rule_decisions: Decision[];
    violations?: Violation[];
    [key: string]: unknown;
  };
};
export type Review = {
  provider: string;
  verdict: string;
  summary: string;
  findings: { rule_id: string; reason: string; suggestion: string }[];
  limitations: string[];
};
export type ProgressItem = {
  id: string;
  source_key?: string;
  title: string;
  criterion: string;
  area: string;
  included: boolean;
  source: { path: string; line: number; excerpt: string; sha256: string };
  implementation_status: "unknown" | "partial" | "implemented" | "not_implemented";
  implementation_note?: string;
  evidence: { path: string; line: number; excerpt?: string; sha256?: string; note: string } | null;
  verification_status: "unverified" | "verified";
  verification_note: string;
  stale_evidence?: boolean;
  reviewed_documents?: Record<string, string>;
  stale_requirement?: boolean;
  doc_marked_done?: boolean;
  test_patterns?: string[];
  doc_claim?: "unbacked" | null;
  duplicates?: { path: string; line: number; excerpt: string; criterion: string }[];
  effective_status?: ProgressItem["implementation_status"] | "excluded";
};
export type ProgressFieldError = { id: string; field: string; message: string };
export type ChangeCounts = Partial<Record<"gained" | "regressed" | "excluded" | "reincluded" | "added" | "removed", number>>;
export type ProgressHistory = {
  snapshots: {
    at: string;
    version: number;
    head: string;
    total: number;
    counts: Record<string, number>;
    changes?: ChangeCounts | null;
    complete_delta?: number | null;
  }[];
  since_save: null | ({
    since: string;
    version: number;
    complete_delta: number;
    counts: ChangeCounts;
  } & Record<"gained" | "regressed" | "excluded" | "reincluded" | "added" | "removed", { id: string; title: string }[]>);
};
export type TestLink = {
  patterns: string[];
  matched: number;
  passed: number;
  failed: number;
  skipped: number;
  failing: string[];
  no_match: boolean;
  code_newer?: boolean;
};
export type TestLinks = {
  format: string;
  file: string;
  modified: string;
  total: number;
  remembered?: boolean;
  items: Record<string, TestLink>;
};
export type LinkIssue = {
  path: string;
  line: number;
  target: string;
  kind: "link" | "path" | "document";
  confidence?: "high" | "low";
  message: string;
};
export type LinkReport = {
  documents: string[];
  checked: number;
  issues: LinkIssue[];
  truncated: boolean;
  limitations: string;
};
export type ProjectDocument = { path: string; tracked: boolean; bytes: number };
export type EvidenceCandidate = { path: string; line: number; excerpt: string };
export type DocumentKind = "current" | "future" | "past" | "reference";
export type ProgressBaseline = {
  repository: string;
  documents: Record<string, string>;
  document_kinds?: Record<string, DocumentKind>;
  requirements: ProgressItem[];
  version?: number;
};
export type ProgressReport = {
  repository: string;
  version: number;
  at: string;
  head: string;
  stale_documents: string[];
  document_kinds?: Record<string, DocumentKind>;
  stale_context_documents?: string[];
  total: number;
  counts: Record<string, number>;
  items: ProgressItem[];
  doc_claims_unbacked?: number;
  test_pattern_hints?: Record<string, string[]>;
  limitations: string;
};
export interface Bridge {
  initialize: () => void;
  setProgressDirty?: (dirty: boolean) => void;
  chooseRepository: () => void;
  startScan: (path: string, base: string) => void;
  previewReview: () => void;
  startReview: (provider: string, path: string) => void;
  cancelReview: () => void;
  exportReport: (kind: string) => void;
  previewPolicy: (path: string, preset: string) => void;
  createPolicy: (path: string, preset: string) => void;
  checkProgressLinks: (path: string, requestId?: string) => void;
  loadTestResults: (path: string, requestId?: string) => void;
  forgetTestResults: (path: string) => void;
  exportProgress: (path: string, kind: string, requestId?: string) => void;
  openDocument: (relative: string) => void;
  listProjectDocs: (path: string, requestId?: string) => void;
  cacheProgressDraft?: (path: string, payloadJson: string, requestId: string) => void;
  discardProgressDraft?: (path: string, requestId: string) => void;
  previewProgress: (path: string, selectedJson: string, requestId?: string) => void;
  saveProgress: (path: string, payloadJson: string, requestId?: string) => void;
  inspectProgress: (path: string, requestId?: string) => void;
  suggestProgressEvidence: (path: string, itemJson: string, requestId?: string) => void;
  event: { connect: (fn: (message: string) => void) => void };
}
declare global {
  interface Window {
    qt?: { webChannelTransport: unknown };
    QWebChannel?: new (
      transport: unknown,
      callback: (channel: { objects: { desktop: Bridge } }) => void,
    ) => void;
  }
}
export function connect(onEvent: (event: DesktopEvent) => void): Promise<Bridge | null> {
  if (!window.qt) return Promise.resolve(null);
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "qrc:///qtwebchannel/qwebchannel.js";
    script.onerror = () =>
      reject(new Error("데스크톱 연결을 불러오지 못했습니다."));
    script.onload = () =>
      new window.QWebChannel!(window.qt!.webChannelTransport, (channel) => {
        const bridge = channel.objects.desktop;
        bridge.event.connect((raw) => {
          onEvent(decodeDesktopEvent(raw));
        });
        resolve(bridge);
        bridge.initialize();
      });
    document.head.append(script);
  });
}
