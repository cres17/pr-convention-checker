/** Writes must keep their editor and request alive across repository changes. */
export const retainedOperations = ['save', 'extract', 'discard', 'draft-export', 'latest', 'draft-import'] as const;
type RetainedOperation = typeof retainedOperations[number];
export type ProgressOperation = '' | RetainedOperation | 'documents' | 'links' | 'tests';
export type ProgressRequest = Exclude<ProgressOperation, ''> | 'inspect' | 'evidence' | 'export' | 'draft';
const retained = new Set<string>(retainedOperations);
export function retainsEditor(operation: string): operation is RetainedOperation { return retained.has(operation); }
