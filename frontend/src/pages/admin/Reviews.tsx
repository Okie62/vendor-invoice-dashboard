import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ClipboardList, AlertTriangle } from 'lucide-react';
import { getReviews, getFormats } from '../../lib/api';
import type { ReviewItem, FormatDef } from '../../lib/api';

export default function Reviews() {
  const [status, setStatus] = useState('pending');
  const [selectedReview, setSelectedReview] = useState<ReviewItem | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  const { data: reviews = [], isLoading, error } = useQuery({
    queryKey: ['reviews', status],
    queryFn: async () => {
      try {
        const result = await getReviews(status);
        setApiError(null);
        return result;
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Unknown error';
        setApiError(msg);
        return [];
      }
    },
  });

  const { data: formats = [] } = useQuery({
    queryKey: ['formats'],
    queryFn: async () => {
      try {
        return await getFormats();
      } catch {
        return [];
      }
    },
  });

  const isStub = apiError?.includes('404') || apiError?.includes('not found');

  return (
    <div className="min-h-full p-3 sm:p-6" style={{ backgroundColor: 'var(--th-surface-1)' }}>
      <div className="mb-4 flex items-center gap-2">
        <ClipboardList className="h-6 w-6" style={{ color: 'var(--color-brand)' }} />
        <h1 className="text-xl font-semibold" style={{ color: 'var(--th-text-primary)' }}>Format Review</h1>
      </div>

      {isStub && (
        <div className="mb-4 p-4 rounded-card flex items-start gap-3" style={{ backgroundColor: 'rgba(245,158,11,0.1)', border: '1px solid var(--th-warning)', color: 'var(--th-warning)' }}>
          <AlertTriangle className="h-5 w-5 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold">Backend endpoints not yet available</p>
            <p className="text-xs mt-1 opacity-80">The Format Review API (/api/reviews, /api/reviews/&lt;id&gt;, /api/reviews/&lt;id&gt;/extract, /api/formats) is being built in parallel. This page is stubbed against the API contract. It will function once the backend is deployed.</p>
          </div>
        </div>
      )}

      {apiError && !isStub && (
        <div className="mb-4 p-3 rounded-card text-sm" style={{ backgroundColor: 'rgba(239,68,68,0.1)', border: '1px solid var(--th-danger)', color: 'var(--th-danger)' }}>
          API Error: {apiError}
        </div>
      )}

      {/* Status filter tabs */}
      <div className="flex gap-1 mb-4" style={{ borderBottom: '1px solid var(--th-border)' }}>
        {['pending', 'verified', 'rejected'].map((s) => (
          <button
            key={s}
            onClick={() => setStatus(s)}
            className="px-4 py-2 text-sm font-medium capitalize border-b-2 transition-colors"
            style={{
              borderBottomColor: status === s ? 'var(--th-accent)' : 'transparent',
              color: status === s ? 'var(--th-accent)' : 'var(--th-text-tertiary)',
            }}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Known formats */}
      {formats.length > 0 && (
        <div className="mb-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--th-text-tertiary)' }}>
            Known Formats ({formats.length})
          </h3>
          <div className="flex flex-wrap gap-2">
            {formats.map((f) => (
              <span key={f.id} className="text-xs px-2 py-1 rounded-full" style={{ backgroundColor: 'var(--th-surface-2)', color: 'var(--th-text-secondary)', border: '1px solid var(--th-border)' }}>
                {f.vendor}: {f.name} v{f.version}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Review queue */}
      {isLoading && <p className="text-sm" style={{ color: 'var(--th-text-tertiary)' }}>Loading...</p>}

      {!isLoading && reviews.length === 0 && !isStub && (
        <p className="text-sm py-8 text-center" style={{ color: 'var(--th-text-tertiary)' }}>
          No {status} reviews.
        </p>
      )}

      {reviews.length > 0 && (
        <div className="grid gap-3">
          {reviews.map((r) => (
            <div
              key={r.id}
              className="p-4 rounded-card cursor-pointer transition-colors"
              style={{
                backgroundColor: selectedReview?.id === r.id ? 'var(--th-active)' : 'var(--th-surface-0)',
                border: `1px solid ${selectedReview?.id === r.id ? 'var(--th-border-strong)' : 'var(--th-border)'}`,
              }}
              onClick={() => setSelectedReview(selectedReview?.id === r.id ? null : r)}
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold" style={{ color: 'var(--th-text-primary)' }}>#{r.invoice_id}</span>
                  <span className="text-xs px-2 py-0.5 rounded-full" style={{ backgroundColor: 'var(--th-surface-2)', color: 'var(--th-text-tertiary)' }}>{r.vendor}</span>
                </div>
                <span className="text-xs" style={{ color: 'var(--th-text-quaternary)' }}>
                  {(r.confidence * 100).toFixed(0)}% confidence
                </span>
              </div>

              {/* Detail drawer */}
              {selectedReview?.id === r.id && (
                <div className="mt-3 pt-3" style={{ borderTop: '1px solid var(--th-border)' }}>
                  <h4 className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--th-text-tertiary)' }}>Extracted Text</h4>
                  <pre className="p-3 rounded-lg font-mono text-xs whitespace-pre-wrap max-h-[200px] overflow-auto mb-3"
                    style={{ backgroundColor: 'var(--th-surface-2)', color: 'var(--th-text-secondary)', border: '1px solid var(--th-border)' }}>
                    {r.extracted_text}
                  </pre>

                  <h4 className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--th-text-tertiary)' }}>Parsed Data</h4>
                  <div className="p-3 rounded-lg font-mono text-xs whitespace-pre-wrap max-h-[200px] overflow-auto mb-3"
                    style={{ backgroundColor: 'var(--th-surface-2)', color: 'var(--th-text-secondary)', border: '1px solid var(--th-border)' }}>
                    {JSON.stringify(r.parsed_data, null, 2)}
                  </div>

                  <div className="flex gap-2">
                    <button className="px-4 py-1.5 text-xs font-semibold text-white rounded-comfortable" style={{ backgroundColor: 'var(--color-brand)' }}>
                      Verify
                    </button>
                    <button className="px-4 py-1.5 text-xs rounded-comfortable" style={{ backgroundColor: 'var(--th-surface-2)', color: 'var(--th-text-tertiary)', border: '1px solid var(--th-border)' }}>
                      Edit Fields
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Empty state when backend is missing */}
      {!isLoading && reviews.length === 0 && isStub && (
        <div className="text-center py-12" style={{ color: 'var(--th-text-tertiary)' }}>
          <ClipboardList className="h-12 w-12 mx-auto mb-3 opacity-40" />
          <p className="text-sm">Format Review queue will appear here once the backend is deployed.</p>
          <p className="text-xs mt-1">Expected endpoints: GET /api/reviews, GET /api/reviews/&lt;id&gt;, PATCH /api/reviews/&lt;id&gt;, POST /api/reviews/&lt;id&gt;/extract, GET /api/formats</p>
        </div>
      )}
    </div>
  );
}