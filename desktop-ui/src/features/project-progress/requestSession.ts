import type { ProgressEvent } from "../../events";
export type ProgressRequest = "documents" | "extract" | "save" | "inspect" | "links" | "tests" | "evidence" | "export" | "draft" | "discard";
const responses: Record<ProgressEvent["type"], ProgressRequest[]> = {
    progressDocs: ["documents", "discard"], progressPreview: ["extract"], progressSaved: ["save"],
    progressReport: ["save", "inspect"], progressHistory: ["save", "inspect"],
    progressTests: ["tests", "inspect"], progressTestsCancelled: ["tests"],
    progressLinks: ["links"], progressEvidence: ["evidence"], progressExported: ["export"],
    progressDraftCached: ["draft"], progressDraftError: ["draft"], progressDraftDiscarded: ["discard"],
    progressError: ["documents", "extract", "save", "inspect", "links", "tests", "evidence", "export", "discard"],
};
/** Requests are scoped to one editor visit, and only the latest request per purpose wins. */
export class ProgressRequests {
    private session = crypto.randomUUID();
    private serial = 0;
    private latest = new Map<ProgressRequest, string>();
    reset() { this.session = crypto.randomUUID(); this.latest.clear(); }
    start(purpose: ProgressRequest) {
        const id = `${this.session}:${++this.serial}`;
        this.latest.set(purpose, id);
        return id;
    }
    cancel(purpose: ProgressRequest) { this.latest.delete(purpose); }
    token(purpose: ProgressRequest) { return this.latest.get(purpose); }
    leave() {
        for (const purpose of ["documents", "inspect", "links", "tests", "evidence", "export"] as const)
            this.cancel(purpose);
    }
    invalidateReads() {
        for (const purpose of ["inspect", "links", "tests", "evidence"] as const)
            this.latest.delete(purpose);
    }
    complete(event: ProgressEvent) {
        if (!event.request_done || !event.request_id)
            return;
        for (const [purpose, id] of this.latest)
            if (id === event.request_id)
                this.latest.delete(purpose);
    }
    accepts(event: ProgressEvent) {
        // In-memory fixtures and older direct API callers may omit metadata. The wire decoder requires it.
        if (event.request_id === undefined)
            return true;
        return responses[event.type].some((purpose) => this.latest.get(purpose) === event.request_id);
    }
}
