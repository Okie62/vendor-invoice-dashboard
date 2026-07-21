import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';
import {
  ClipboardList,
  AlertTriangle,
  Loader2,
  Sparkles,
  CheckCircle2,
  XCircle,
  Eye,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import PdfReviewViewer from '../../components/PdfReviewViewer';
import {
  getReviews,
  getReview,
  getFormats,
  autoExtractReview,
  extractReview,
  extractSelection,
  patchReview,
  type ReviewItem,
  type ExtractedFields,
} from '../../lib/api';

const STATUS_TABS = ['pending', 'in_review', 'verified', 'dismissed'] as const;

const REASON_STYLES: Record<string, { bg: string; text: string; border: string; label: string }> = {
  no_parser: {
    bg: 'rgba(245,158,11,0.12)',
    text: '#f59e0b',
    border: 'rgba(245,158,11,0.25)',
    label: 'no_parser',
  },
  new_format: {
    bg: 'rgba(59,130,246,0.12)',
    text: '#3b82f6',
    border: 'rgba(59,130,246,0.25)',
    label: 'new_format',
  },
  no_body: {
    bg: 'rgba(239,68,68,0.12)',
    text: '#ef4444',
    border: 'rgba(239,68,68,0.25)',
    label: 'no_body',
  },
};

const STATUS_BADGE: Record<string, { bg: string; text: string; border: string }> = {
  pending: { bg: 'rgba(245,158,11,0.12)', text: '#f59e0b', border: 'rgba(245,158,11,0.25)' },
  in_review: { bg: 'rgba(99,102,241,0.12)', text: '#6366f1', border: 'rgba(99,102,241,0.25)' },
  verified: { bg: 'rgba(39,166,68,0.12)', text: '#27a644', border: 'rgba(39,166,68,0.25)' },
  dismissed: { bg: 'rgba(148,163,184,0.12)', text: '#94a3b8', border: 'rgba(148,163,184,0.25)' },
  parsed: { bg: 'rgba(57,216,189,0.12)', text: '#39d8bd', border: 'rgba(57,216,189,0.25)' },
};

type FormState = {
  invoice_id: string;
  billing_period: string;
  invoice_date: string;
  due_date: string;
  vendor_name: string;
  previous_balance: string;
  credit_card_surcharges: string;
  payment_received: string;
  new_charges: string;
  outstanding_balance: string;
};

const EMPTY_FORM: FormState = {
  invoice_id: '',
  billing_period: '',
  invoice_date: '',
  due_date: '',
  vendor_name: '',
  previous_balance: '',
  credit_card_surcharges: '',
  payment_received: '',
  new_charges: '',
  outstanding_balance: '',
};

function fieldsToForm(fields: ExtractedFields | null | undefined): FormState {
  if (!fields) return { ...EMPTY_FORM };
  const num = (v: number | null | undefined) =>
    v === null || v === undefined || Number.isNaN(v) ? '' : String(v);
  return {
    invoice_id: fields.invoice_id ?? '',
    billing_period: fields.billing_period ?? '',
    invoice_date: fields.invoice_date ?? '',
    due_date: fields.due_date ?? '',
    vendor_name: fields.vendor_name ?? '',
    previous_balance: num(fields.previous_balance),
    credit_card_surcharges: num(fields.credit_card_surcharges),
    payment_received: num(fields.payment_received),
    new_charges: num(fields.new_charges),
    outstanding_balance: num(fields.outstanding_balance),
  };
}

/** Merge non-null extracted fields into existing form; return list of updated keys. */
function mergeFieldsIntoForm(
  prev: FormState,
  fields: ExtractedFields,
): { next: FormState; updated: string[] } {
  const next = { ...prev };
  const updated: string[] = [];
  const num = (v: number | null | undefined) =>
    v === null || v === undefined || Number.isNaN(v) ? null : String(v);

  const setStr = (key: keyof FormState, val: string | null | undefined) => {
    if (val === null || val === undefined || val === '') return;
    next[key] = val;
    updated.push(key);
  };
  const setNum = (key: keyof FormState, val: number | null | undefined) => {
    const s = num(val);
    if (s === null) return;
    next[key] = s;
    updated.push(key);
  };

  setStr('invoice_id', fields.invoice_id);
  setStr('billing_period', fields.billing_period);
  setStr('invoice_date', fields.invoice_date);
  setStr('due_date', fields.due_date);
  setStr('vendor_name', fields.vendor_name);
  setNum('previous_balance', fields.previous_balance);
  setNum('credit_card_surcharges', fields.credit_card_surcharges);
  setNum('payment_received', fields.payment_received);
  setNum('new_charges', fields.new_charges);
  setNum('outstanding_balance', fields.outstanding_balance);

  return { next, updated };
}

function formToOverrides(form: FormState): Record<string, unknown> {
  const parseNum = (s: string): number | null => {
    const t = s.trim();
    if (!t) return null;
    const n = Number(t);
    return Number.isFinite(n) ? n : null;
  };
  return {
    invoice_id: form.invoice_id.trim() || null,
    billing_period: form.billing_period.trim() || null,
    invoice_date: form.invoice_date.trim() || null,
    due_date: form.due_date.trim() || null,
    vendor_name: form.vendor_name.trim() || null,
    previous_balance: parseNum(form.previous_balance),
    credit_card_surcharges: parseNum(form.credit_card_surcharges),
    payment_received: parseNum(form.payment_received),
    new_charges: parseNum(form.new_charges),
    outstanding_balance: parseNum(form.outstanding_balance),
  };
}

function axiosMessage(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const status = err.response?.status;
    const data = err.response?.data as { error?: string; detail?: string; message?: string } | undefined;
    const detail = data?.error || data?.detail || data?.message || err.message;
    if (status === 503) return 'LLM extraction not configured. Set XAI_API_KEY on the server.';
    if (status === 400) {
      if (typeof detail === 'string' && /no document text|no text|empty/i.test(detail)) {
        return 'No document text found for this invoice.';
      }
      return typeof detail === 'string' ? detail : 'No document text found for this invoice.';
    }
    if (status === 502) return typeof detail === 'string' ? detail : 'LLM extraction failed.';
    if (status === 404) return 'Review not found.';
    if (typeof detail === 'string' && detail) return detail;
  }
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

function fmtTimestamp(s: string | null | undefined): string {
  if (!s) return '—';
  try {
    const d = new Date(s.includes('T') ? s : s.replace(' ', 'T') + 'Z');
    if (Number.isNaN(d.getTime())) return s;
    return d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  } catch {
    return s;
  }
}

function Badge({
  label,
  bg,
  text,
  border,
}: {
  label: string;
  bg: string;
  text: string;
  border: string;
}) {
  return (
    <span
      className="inline-flex items-center text-[11px] font-medium px-2 py-0.5 rounded-full capitalize"
      style={{ backgroundColor: bg, color: text, border: `1px solid ${border}` }}
    >
      {label}
    </span>
  );
}

export default function Reviews() {
  const { user } = useAuth();
  const isAdmin = !!user?.is_admin;
  const queryClient = useQueryClient();

  const [status, setStatus] = useState<(typeof STATUS_TABS)[number]>('pending');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>({ ...EMPTY_FORM });
  const [hasExtracted, setHasExtracted] = useState(false);
  const [customers, setCustomers] = useState<ExtractedFields['customers']>([]);
  const [lineItems, setLineItems] = useState<ExtractedFields['line_items']>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [rawSelectedText, setRawSelectedText] = useState('');

  const {
    data: reviews = [],
    isLoading,
    error: listError,
    isError: isListError,
  } = useQuery({
    queryKey: ['reviews', status],
    queryFn: () => getReviews(status),
  });

  const { data: formats = [] } = useQuery({
    queryKey: ['formats'],
    queryFn: getFormats,
    retry: false,
  });

  const {
    data: detail,
    isLoading: detailLoading,
    error: detailError,
    isError: isDetailError,
  } = useQuery({
    queryKey: ['review', selectedId],
    queryFn: () => getReview(selectedId as number),
    enabled: selectedId !== null,
    retry: false,
  });

  // Reset extract form when switching reviews
  useEffect(() => {
    setForm({ ...EMPTY_FORM });
    setHasExtracted(false);
    setCustomers([]);
    setLineItems([]);
    setActionError(null);
    setSuccessMsg(null);
    setRawSelectedText('');
  }, [selectedId]);

  const invalidateReviews = () => {
    queryClient.invalidateQueries({ queryKey: ['reviews'] });
    if (selectedId !== null) {
      queryClient.invalidateQueries({ queryKey: ['review', selectedId] });
    }
  };

  const applyExtraction = (fields: ExtractedFields, mode: 'replace' | 'merge') => {
    if (mode === 'replace') {
      setForm(fieldsToForm(fields));
      setCustomers(fields.customers || []);
      setLineItems(fields.line_items || []);
      setHasExtracted(true);
      setSuccessMsg('Fields extracted — review and edit before verifying.');
      return;
    }

    const { next, updated } = mergeFieldsIntoForm(form, fields);
    setForm(next);
    if (fields.customers?.length) {
      setCustomers(fields.customers);
      if (!updated.includes('customers')) updated.push('customers');
    }
    if (fields.line_items?.length) {
      setLineItems(fields.line_items);
      if (!updated.includes('line_items')) updated.push('line_items');
    }
    setHasExtracted(true);
    if (updated.length) {
      setSuccessMsg(`Added: ${updated.join(', ')}`);
    } else {
      setSuccessMsg('No new fields found in selection.');
    }
  };

  const autoExtractMutation = useMutation({
    mutationFn: (id: number) => autoExtractReview(id),
    onSuccess: (data) => {
      setActionError(null);
      applyExtraction(data.extracted_fields, 'replace');
    },
    onError: (err) => {
      setSuccessMsg(null);
      setActionError(axiosMessage(err, 'Auto-extract failed.'));
    },
  });

  const selectionMutation = useMutation({
    mutationFn: (args: { id: number; body: { text?: string; image?: string; mime_type?: string } }) =>
      extractSelection(args.id, args.body),
    onSuccess: (data) => {
      setActionError(null);
      applyExtraction(data.extracted_fields, 'merge');
      setRawSelectedText('');
      try {
        window.getSelection()?.removeAllRanges();
      } catch {
        /* ignore */
      }
    },
    onError: (err) => {
      setSuccessMsg(null);
      setActionError(axiosMessage(err, 'Selection extract failed.'));
    },
  });

  const verifyMutation = useMutation({
    mutationFn: async (id: number) => {
      const overrides = formToOverrides(form);
      if (customers.length) overrides.customers = customers;
      if (lineItems.length) overrides.line_items = lineItems;
      const result = await extractReview(id, overrides);
      try {
        await patchReview(id, { status: 'verified' });
      } catch {
        // ignore if already verified by extract
      }
      return result;
    },
    onSuccess: (data) => {
      setActionError(null);
      setSuccessMsg(`Verified and applied as invoice ${data.invoice_id}.`);
      invalidateReviews();
      setTimeout(() => {
        setSelectedId(null);
        setSuccessMsg(null);
      }, 1800);
    },
    onError: (err) => {
      setSuccessMsg(null);
      setActionError(axiosMessage(err, 'Verify failed.'));
    },
  });

  const dismissMutation = useMutation({
    mutationFn: (id: number) => patchReview(id, { status: 'dismissed' }),
    onSuccess: () => {
      setActionError(null);
      setSuccessMsg('Review dismissed.');
      invalidateReviews();
      setSelectedId(null);
    },
    onError: (err) => {
      setSuccessMsg(null);
      setActionError(axiosMessage(err, 'Dismiss failed.'));
    },
  });

  const inReviewMutation = useMutation({
    mutationFn: (id: number) => patchReview(id, { status: 'in_review' }),
    onSuccess: () => {
      setActionError(null);
      setSuccessMsg('Marked in review.');
      invalidateReviews();
    },
    onError: (err) => {
      setSuccessMsg(null);
      setActionError(axiosMessage(err, 'Could not update status.'));
    },
  });

  const listErrorMsg = useMemo(() => {
    if (!isListError || !listError) return null;
    return axiosMessage(listError, 'Failed to load reviews.');
  }, [isListError, listError]);

  const selectedReview: ReviewItem | undefined = reviews.find((r) => r.id === selectedId);

  const updateField = (key: keyof FormState, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const inputStyle = {
    backgroundColor: 'var(--th-surface-0)',
    border: '1px solid var(--th-border-strong)',
    color: 'var(--th-text-primary)',
  } as const;

  const labelStyle = { color: 'var(--th-text-tertiary)' } as const;

  const handleTextSelected = (text: string) => {
    if (!isAdmin || selectedId === null || !text.trim()) return;
    setActionError(null);
    setSuccessMsg(null);
    selectionMutation.mutate({ id: selectedId, body: { text: text.trim() } });
  };

  const handleAreaSelected = (base64Png: string) => {
    if (!isAdmin || selectedId === null || !base64Png.trim()) return;
    setActionError(null);
    setSuccessMsg(null);
    selectionMutation.mutate({
      id: selectedId,
      body: { image: base64Png.trim(), mime_type: 'image/png' },
    });
  };

  const handleRawTextExtract = () => {
    const text = rawSelectedText.trim() || (typeof window !== 'undefined' ? window.getSelection()?.toString().trim() : '') || '';
    if (!text) {
      setActionError('Select some raw text first, then click Extract Selection.');
      return;
    }
    handleTextSelected(text);
  };

  const fieldLabels: [keyof FormState, string][] = [
    ['invoice_id', 'Invoice ID'],
    ['billing_period', 'Billing period'],
    ['invoice_date', 'Invoice date'],
    ['due_date', 'Due date'],
    ['vendor_name', 'Vendor name'],
    ['previous_balance', 'Previous balance'],
    ['credit_card_surcharges', 'CC surcharges'],
    ['payment_received', 'Payment received'],
    ['new_charges', 'New charges'],
    ['outstanding_balance', 'Outstanding balance'],
  ];

  return (
    <div className="min-h-full p-3 sm:p-6" style={{ backgroundColor: 'var(--th-surface-1)' }}>
      <div className="mb-2 flex items-center gap-2">
        <ClipboardList className="h-6 w-6" style={{ color: 'var(--color-brand)' }} />
        <h1 className="text-xl font-semibold" style={{ color: 'var(--th-text-primary)' }}>
          Format Review
        </h1>
      </div>
      <p className="mb-5 text-sm" style={{ color: 'var(--th-text-tertiary)' }}>
        Review unrecognized invoice formats. Select text or areas on the document, extract fields, edit, then verify.
      </p>

      {listErrorMsg && (
        <div
          className="mb-4 p-3 rounded-card flex items-start gap-2 text-sm"
          style={{
            backgroundColor: 'rgba(239,68,68,0.1)',
            border: '1px solid var(--th-danger)',
            color: 'var(--th-danger)',
          }}
        >
          <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" />
          <span>{listErrorMsg}</span>
        </div>
      )}

      {/* Status filter tabs */}
      <div className="flex flex-wrap gap-1 mb-4" style={{ borderBottom: '1px solid var(--th-border)' }}>
        {STATUS_TABS.map((s) => (
          <button
            key={s}
            onClick={() => {
              setStatus(s);
              setSelectedId(null);
            }}
            className="px-4 py-2 text-sm font-medium capitalize border-b-2 transition-colors"
            style={{
              borderBottomColor: status === s ? 'var(--th-accent)' : 'transparent',
              color: status === s ? 'var(--th-accent)' : 'var(--th-text-tertiary)',
            }}
          >
            {s.replace('_', ' ')}
          </button>
        ))}
      </div>

      {/* Known formats */}
      {formats.length > 0 && (
        <div className="mb-4">
          <h3
            className="text-xs font-semibold uppercase tracking-wider mb-2"
            style={{ color: 'var(--th-text-tertiary)' }}
          >
            Known Formats ({formats.length})
          </h3>
          <div className="flex flex-wrap gap-2">
            {formats.map((f) => (
              <span
                key={f.id}
                className="text-xs px-2 py-1 rounded-full"
                style={{
                  backgroundColor: 'var(--th-surface-2)',
                  color: 'var(--th-text-secondary)',
                  border: '1px solid var(--th-border)',
                }}
                title={f.format_fingerprint}
              >
                {f.vendor_name}: {f.parser_name} ({f.sample_count} sample
                {f.sample_count !== 1 ? 's' : ''})
              </span>
            ))}
          </div>
        </div>
      )}

      {isLoading && (
        <div className="flex items-center gap-2 py-8 justify-center text-sm" style={{ color: 'var(--th-text-tertiary)' }}>
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading reviews…
        </div>
      )}

      {!isLoading && reviews.length === 0 && !listErrorMsg && (
        <p className="text-sm py-8 text-center" style={{ color: 'var(--th-text-tertiary)' }}>
          No {status.replace('_', ' ')} reviews.
        </p>
      )}

      {reviews.length > 0 && (
        <div className="grid gap-3">
          {reviews.map((r) => {
            const expanded = selectedId === r.id;
            const reason = REASON_STYLES[r.detection_reason] || {
              bg: 'rgba(148,163,184,0.12)',
              text: '#94a3b8',
              border: 'rgba(148,163,184,0.25)',
              label: r.detection_reason || 'unknown',
            };
            const st = STATUS_BADGE[r.status] || STATUS_BADGE.pending;
            const pdfPath = detail?.review?.pdf_path ?? r.pdf_path;

            return (
              <div
                key={r.id}
                className="rounded-card transition-colors"
                style={{
                  backgroundColor: expanded ? 'var(--th-active)' : 'var(--th-surface-0)',
                  border: `1px solid ${expanded ? 'var(--th-border-strong)' : 'var(--th-border)'}`,
                }}
              >
                <button
                  type="button"
                  className="w-full text-left p-4"
                  onClick={() => setSelectedId(expanded ? null : r.id)}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2 mb-1.5">
                        <span className="text-sm font-semibold" style={{ color: 'var(--th-text-primary)' }}>
                          #{r.invoice_id}
                        </span>
                        <Badge
                          label={r.vendor_name || 'Unknown vendor'}
                          bg="var(--th-surface-2)"
                          text="var(--th-text-secondary)"
                          border="var(--th-border)"
                        />
                        <Badge label={reason.label} bg={reason.bg} text={reason.text} border={reason.border} />
                        <Badge label={r.status.replace('_', ' ')} bg={st.bg} text={st.text} border={st.border} />
                      </div>
                      <p className="text-xs" style={{ color: 'var(--th-text-quaternary)' }}>
                        Detected {fmtTimestamp(r.detected_at)}
                        {r.invoice_source ? ` · ${r.invoice_source}` : ''}
                      </p>
                    </div>
                    <span style={{ color: 'var(--th-text-quaternary)' }}>
                      {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                    </span>
                  </div>
                </button>

                {expanded && (
                  <div className="px-4 pb-4 pt-0" style={{ borderTop: '1px solid var(--th-border)' }}>
                    <div className="pt-3 space-y-3">
                      {actionError && (
                        <div
                          className="p-3 rounded-lg text-sm flex items-start gap-2"
                          style={{
                            backgroundColor: 'rgba(239,68,68,0.1)',
                            border: '1px solid var(--th-danger)',
                            color: 'var(--th-danger)',
                          }}
                        >
                          <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" />
                          <span>{actionError}</span>
                        </div>
                      )}

                      {successMsg && (
                        <div
                          className="p-3 rounded-lg text-sm flex items-start gap-2"
                          style={{
                            backgroundColor: 'rgba(39,166,68,0.12)',
                            border: '1px solid rgba(39,166,68,0.35)',
                            color: '#27a644',
                          }}
                        >
                          <CheckCircle2 className="h-4 w-4 flex-shrink-0 mt-0.5" />
                          <span>{successMsg}</span>
                        </div>
                      )}

                      {r.notes && (
                        <p className="text-xs" style={{ color: 'var(--th-text-secondary)' }}>
                          Notes: {r.notes}
                        </p>
                      )}

                      {/* Split view: document | fields */}
                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 min-h-[420px]">
                        {/* LEFT: Document */}
                        <div
                          className="flex flex-col min-h-[360px] max-h-[70vh] overflow-hidden rounded-lg"
                          style={{ border: '1px solid var(--th-border)', backgroundColor: 'var(--th-surface-0)' }}
                        >
                          <div
                            className="px-3 py-2 text-xs font-semibold uppercase tracking-wider"
                            style={{
                              color: 'var(--th-text-tertiary)',
                              borderBottom: '1px solid var(--th-border)',
                              backgroundColor: 'var(--th-surface-1)',
                            }}
                          >
                            Document
                          </div>
                          <div className="flex-1 min-h-0 overflow-auto p-2">
                            {detailLoading && (
                              <div
                                className="flex items-center gap-2 text-xs py-8 justify-center"
                                style={{ color: 'var(--th-text-tertiary)' }}
                              >
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                Loading document…
                              </div>
                            )}
                            {isDetailError && (
                              <p className="text-xs p-3" style={{ color: 'var(--th-danger)' }}>
                                {axiosMessage(detailError, 'Could not load review detail.')}
                              </p>
                            )}
                            {!detailLoading && (
                              <>
                                {pdfPath ? (
                                  <div className="h-full min-h-[320px]">
                                    <PdfReviewViewer
                                      invoiceId={r.invoice_id}
                                      pdfPath={pdfPath}
                                      onTextSelected={isAdmin ? handleTextSelected : undefined}
                                      onAreaSelected={isAdmin ? handleAreaSelected : undefined}
                                      extracting={selectionMutation.isPending}
                                    />
                                  </div>
                                ) : (
                                  <div className="space-y-2">
                                    <p className="text-xs" style={{ color: 'var(--th-text-tertiary)' }}>
                                      No file on disk — select from raw text below.
                                    </p>
                                    <pre
                                      className="p-3 rounded-lg font-mono text-xs whitespace-pre-wrap max-h-[360px] overflow-auto select-text"
                                      style={{
                                        backgroundColor: 'var(--th-surface-2)',
                                        color: 'var(--th-text-secondary)',
                                        border: '1px solid var(--th-border)',
                                      }}
                                      onMouseUp={() => {
                                        const t = window.getSelection()?.toString().trim() || '';
                                        setRawSelectedText(t);
                                      }}
                                    >
                                      {detail?.raw_text?.trim()
                                        ? detail.raw_text
                                        : '(No text extracted from document)'}
                                    </pre>
                                    {isAdmin && (
                                      <button
                                        type="button"
                                        disabled={selectionMutation.isPending || !rawSelectedText}
                                        onClick={handleRawTextExtract}
                                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white rounded-comfortable disabled:opacity-50"
                                        style={{ backgroundColor: 'var(--color-brand)' }}
                                      >
                                        {selectionMutation.isPending ? (
                                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                        ) : (
                                          <Sparkles className="h-3.5 w-3.5" />
                                        )}
                                        Extract Selection
                                      </button>
                                    )}
                                  </div>
                                )}

                                {/* Always offer collapsible raw text under PDF when available */}
                                {pdfPath && detail?.raw_text?.trim() && (
                                  <details className="mt-2">
                                    <summary
                                      className="text-[11px] cursor-pointer uppercase tracking-wider"
                                      style={{ color: 'var(--th-text-quaternary)' }}
                                    >
                                      Raw text fallback
                                    </summary>
                                    <div className="mt-1 space-y-2">
                                      <pre
                                        className="p-2 rounded-lg font-mono text-[11px] whitespace-pre-wrap max-h-[160px] overflow-auto select-text"
                                        style={{
                                          backgroundColor: 'var(--th-surface-2)',
                                          color: 'var(--th-text-secondary)',
                                          border: '1px solid var(--th-border)',
                                        }}
                                        onMouseUp={() => {
                                          const t = window.getSelection()?.toString().trim() || '';
                                          setRawSelectedText(t);
                                        }}
                                      >
                                        {detail.raw_text}
                                      </pre>
                                      {isAdmin && rawSelectedText && (
                                        <button
                                          type="button"
                                          disabled={selectionMutation.isPending}
                                          onClick={handleRawTextExtract}
                                          className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold text-white rounded disabled:opacity-50"
                                          style={{ backgroundColor: 'var(--color-brand)' }}
                                        >
                                          {selectionMutation.isPending ? (
                                            <Loader2 className="h-3 w-3 animate-spin" />
                                          ) : (
                                            <Sparkles className="h-3 w-3" />
                                          )}
                                          Extract Selection
                                        </button>
                                      )}
                                    </div>
                                  </details>
                                )}
                              </>
                            )}
                          </div>
                        </div>

                        {/* RIGHT: Extracted fields */}
                        <div
                          className="flex flex-col min-h-[360px] max-h-[70vh] overflow-hidden rounded-lg"
                          style={{ border: '1px solid var(--th-border)', backgroundColor: 'var(--th-surface-0)' }}
                        >
                          <div
                            className="flex flex-wrap items-center justify-between gap-2 px-3 py-2"
                            style={{
                              borderBottom: '1px solid var(--th-border)',
                              backgroundColor: 'var(--th-surface-1)',
                            }}
                          >
                            <span
                              className="text-xs font-semibold uppercase tracking-wider"
                              style={{ color: 'var(--th-text-tertiary)' }}
                            >
                              Extracted fields
                            </span>
                            <div className="flex flex-wrap gap-1.5">
                              {isAdmin && (
                                <button
                                  type="button"
                                  disabled={autoExtractMutation.isPending || selectedId === null}
                                  onClick={() => {
                                    setActionError(null);
                                    setSuccessMsg(null);
                                    if (selectedId !== null) autoExtractMutation.mutate(selectedId);
                                  }}
                                  className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-semibold text-white rounded disabled:opacity-50"
                                  style={{ backgroundColor: 'var(--color-brand)' }}
                                >
                                  {autoExtractMutation.isPending ? (
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  ) : (
                                    <Sparkles className="h-3.5 w-3.5" />
                                  )}
                                  {autoExtractMutation.isPending ? 'Extracting…' : 'Auto-Extract'}
                                </button>
                              )}
                              {isAdmin && hasExtracted && (
                                <button
                                  type="button"
                                  disabled={verifyMutation.isPending || selectedId === null}
                                  onClick={() => {
                                    setActionError(null);
                                    if (selectedId !== null) verifyMutation.mutate(selectedId);
                                  }}
                                  className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-semibold text-white rounded disabled:opacity-50"
                                  style={{ backgroundColor: '#27a644' }}
                                >
                                  {verifyMutation.isPending ? (
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  ) : (
                                    <CheckCircle2 className="h-3.5 w-3.5" />
                                  )}
                                  {verifyMutation.isPending ? 'Applying…' : 'Verify & Apply'}
                                </button>
                              )}
                            </div>
                          </div>

                          <div className="flex-1 min-h-0 overflow-auto p-3 space-y-3">
                            {r.extracted_data && (
                              <div>
                                <h4
                                  className="text-[11px] font-semibold uppercase tracking-wider mb-1"
                                  style={{ color: 'var(--th-text-tertiary)' }}
                                >
                                  Detection data
                                </h4>
                                <pre
                                  className="p-2 rounded-lg font-mono text-[11px] whitespace-pre-wrap max-h-[100px] overflow-auto"
                                  style={{
                                    backgroundColor: 'var(--th-surface-2)',
                                    color: 'var(--th-text-secondary)',
                                    border: '1px solid var(--th-border)',
                                  }}
                                >
                                  {JSON.stringify(r.extracted_data, null, 2)}
                                </pre>
                              </div>
                            )}

                            {!hasExtracted && (
                              <p className="text-xs" style={{ color: 'var(--th-text-quaternary)' }}>
                                Auto-extract the full document, or select text/area on the left to populate fields.
                              </p>
                            )}

                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                              {fieldLabels.map(([key, label]) => (
                                <div key={key}>
                                  <label
                                    className="block text-[11px] uppercase tracking-wider mb-1"
                                    style={labelStyle}
                                  >
                                    {label}
                                  </label>
                                  <input
                                    value={form[key]}
                                    onChange={(e) => updateField(key, e.target.value)}
                                    disabled={!isAdmin}
                                    className="w-full px-2.5 py-2 text-sm rounded-comfortable focus:outline-none disabled:opacity-60"
                                    style={inputStyle}
                                  />
                                </div>
                              ))}
                            </div>
                            {(customers.length > 0 || lineItems.length > 0) && (
                              <div className="grid grid-cols-1 gap-3">
                                {customers.length > 0 && (
                                  <div>
                                    <h5 className="text-[11px] uppercase tracking-wider mb-1" style={labelStyle}>
                                      Customers ({customers.length})
                                    </h5>
                                    <pre
                                      className="p-2 rounded-lg font-mono text-[11px] whitespace-pre-wrap max-h-[140px] overflow-auto"
                                      style={{
                                        backgroundColor: 'var(--th-surface-2)',
                                        color: 'var(--th-text-secondary)',
                                        border: '1px solid var(--th-border)',
                                      }}
                                    >
                                      {JSON.stringify(customers, null, 2)}
                                    </pre>
                                  </div>
                                )}
                                {lineItems.length > 0 && (
                                  <div>
                                    <h5 className="text-[11px] uppercase tracking-wider mb-1" style={labelStyle}>
                                      Line items ({lineItems.length})
                                    </h5>
                                    <pre
                                      className="p-2 rounded-lg font-mono text-[11px] whitespace-pre-wrap max-h-[140px] overflow-auto"
                                      style={{
                                        backgroundColor: 'var(--th-surface-2)',
                                        color: 'var(--th-text-secondary)',
                                        border: '1px solid var(--th-border)',
                                      }}
                                    >
                                      {JSON.stringify(lineItems, null, 2)}
                                    </pre>
                                  </div>
                                )}
                              </div>
                            )}

                            {!isAdmin && (
                              <p className="text-xs" style={{ color: 'var(--th-text-quaternary)' }}>
                                Admin role required to extract, verify, or dismiss.
                              </p>
                            )}
                          </div>
                        </div>
                      </div>

                      {/* Bottom actions */}
                      <div className="flex flex-wrap gap-2 pt-1">
                        {isAdmin && (
                          <button
                            type="button"
                            disabled={dismissMutation.isPending || selectedId === null}
                            onClick={() => {
                              setActionError(null);
                              if (selectedId !== null) dismissMutation.mutate(selectedId);
                            }}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-comfortable disabled:opacity-50"
                            style={{
                              backgroundColor: 'var(--th-surface-2)',
                              color: 'var(--th-text-tertiary)',
                              border: '1px solid var(--th-border)',
                            }}
                          >
                            {dismissMutation.isPending ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <XCircle className="h-3.5 w-3.5" />
                            )}
                            Dismiss
                          </button>
                        )}

                        {selectedReview && selectedReview.status === 'pending' && (
                          <button
                            type="button"
                            disabled={inReviewMutation.isPending || selectedId === null}
                            onClick={() => {
                              setActionError(null);
                              if (selectedId !== null) inReviewMutation.mutate(selectedId);
                            }}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-comfortable disabled:opacity-50"
                            style={{
                              backgroundColor: 'var(--th-surface-2)',
                              color: 'var(--th-text-secondary)',
                              border: '1px solid var(--th-border)',
                            }}
                          >
                            {inReviewMutation.isPending ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Eye className="h-3.5 w-3.5" />
                            )}
                            Mark In Review
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
