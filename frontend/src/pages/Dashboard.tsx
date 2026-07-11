import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  DollarSign,
  AlertTriangle,
  Clock,
  CheckCircle2,
  FileText,
  TrendingUp,
  Building2,
  ArrowUpRight,
  ChevronRight,
} from 'lucide-react';
import { getDashboard, getVendors, STATUS_STYLES, type DashboardData, type DBInvoice } from '../lib/api';

const currency = (v: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(v);

const fmtDate = (d: string | null | undefined) => {
  if (!d) return '—';
  try { return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }); }
  catch { return d; }
};

export default function Dashboard() {
  const navigate = useNavigate();

  const { data: dash, isLoading } = useQuery({
    queryKey: ['dashboard'],
    queryFn: getDashboard,
    refetchInterval: 60000,
  });

  const { data: vendors = [] } = useQuery({
    queryKey: ['vendors'],
    queryFn: getVendors,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-brand border-t-transparent" />
      </div>
    );
  }

  const summary = dash?.summary;
  const aging = dash?.aging;
  const recent = dash?.recent_invoices || [];
  const monthly = dash?.monthly_spend || [];

  // Compute aging total for percentages
  const agingBuckets = aging ? [
    { label: 'Current', key: 'current', value: aging.current, color: '#27a644' },
    { label: '1–30 days', key: 'days_1_30', value: aging.days_1_30, color: '#f59e0b' },
    { label: '31–60 days', key: 'days_31_60', value: aging.days_31_60, color: '#f97316' },
    { label: '61–90 days', key: 'days_61_90', value: aging.days_61_90, color: '#ef4444' },
    { label: '90+ days', key: 'days_90_plus', value: aging.days_90_plus, color: '#dc2626' },
    { label: 'No due date', key: 'no_due_date', value: aging.no_due_date, color: '#94a3b8' },
  ] : [];
  const agingTotal = agingBuckets.reduce((s, b) => s + b.value, 0);

  return (
    <div className="min-h-full p-3 sm:p-6 space-y-4 sm:space-y-6" style={{ backgroundColor: 'var(--th-surface-1)' }}>
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold" style={{ color: 'var(--th-accent)' }}>A/P Dashboard</h1>
        <p className="text-sm mt-1" style={{ color: 'var(--th-text-tertiary)' }}>
          Accounts Payable overview — {vendors.length} vendor{vendors.length !== 1 ? 's' : ''}
        </p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <SummaryCard
          icon={<DollarSign className="h-5 w-5" />}
          iconBg="rgba(57,216,189,0.12)"
          iconColor="var(--th-accent)"
          label="Total Outstanding"
          value={currency(summary?.total_outstanding ?? 0)}
        />
        <SummaryCard
          icon={<Clock className="h-5 w-5" />}
          iconBg="rgba(245,158,11,0.12)"
          iconColor="#f59e0b"
          label="Due Soon (7 days)"
          value={currency(summary?.due_soon ?? 0)}
        />
        <SummaryCard
          icon={<AlertTriangle className="h-5 w-5" />}
          iconBg="rgba(239,68,68,0.12)"
          iconColor="#ef4444"
          label="Overdue"
          value={currency(summary?.overdue ?? 0)}
        />
        <SummaryCard
          icon={<CheckCircle2 className="h-5 w-5" />}
          iconBg="rgba(39,166,68,0.12)"
          iconColor="#27a644"
          label="Paid This Month"
          value={currency(summary?.paid_this_month ?? 0)}
        />
      </div>

      {/* A/P Aging + Recent Invoices */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Aging Visualization */}
        <div className="lg:col-span-1 rounded-lg p-5" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}>
          <h2 className="text-sm font-semibold mb-4 flex items-center gap-2" style={{ color: 'var(--th-text-primary)' }}>
            <Clock className="h-4 w-4" style={{ color: 'var(--th-accent)' }} />
            A/P Aging
          </h2>
          {agingTotal === 0 ? (
            <p className="py-6 text-center text-sm" style={{ color: 'var(--th-text-tertiary)' }}>No outstanding invoices</p>
          ) : (
            <div className="space-y-3">
              {/* Stacked bar */}
              <div className="h-4 rounded-full overflow-hidden flex" style={{ backgroundColor: 'var(--th-surface-2)' }}>
                {agingBuckets.filter(b => b.value > 0).map((bucket) => (
                  <div
                    key={bucket.key}
                    style={{
                      width: `${(bucket.value / agingTotal) * 100}%`,
                      backgroundColor: bucket.color,
                      minWidth: bucket.value > 0 ? '4px' : '0',
                    }}
                    title={`${bucket.label}: ${currency(bucket.value)}`}
                  />
                ))}
              </div>
              {/* Legend */}
              <div className="space-y-1.5">
                {agingBuckets.map((bucket) => (
                  <div key={bucket.key} className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2">
                      <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: bucket.color }} />
                      <span style={{ color: 'var(--th-text-tertiary)' }}>{bucket.label}</span>
                    </div>
                    <span className="font-medium" style={{ color: 'var(--th-text-secondary)' }}>
                      {currency(bucket.value)}
                      {agingTotal > 0 && (
                        <span className="ml-1" style={{ color: 'var(--th-text-quaternary)' }}>
                          ({((bucket.value / agingTotal) * 100).toFixed(1)}%)
                        </span>
                      )}
                    </span>
                  </div>
                ))}
              </div>
              <div className="pt-2 border-t flex justify-between text-xs font-semibold" style={{ borderColor: 'var(--th-border)', color: 'var(--th-text-primary)' }}>
                <span>Total Outstanding</span>
                <span>{currency(agingTotal)}</span>
              </div>
            </div>
          )}
        </div>

        {/* Recent Invoices */}
        <div className="lg:col-span-2 rounded-lg" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}>
          <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: '1px solid var(--th-border)' }}>
            <h2 className="text-sm font-semibold flex items-center gap-2" style={{ color: 'var(--th-text-primary)' }}>
              <FileText className="h-4 w-4" style={{ color: 'var(--th-accent)' }} />
              Recent Invoices
            </h2>
            <button
              onClick={() => navigate('/invoices')}
              className="text-xs font-medium flex items-center gap-1"
              style={{ color: 'var(--th-accent)' }}
            >
              View all <ChevronRight className="h-3 w-3" />
            </button>
          </div>
          {recent.length === 0 ? (
            <p className="py-8 text-center text-sm" style={{ color: 'var(--th-text-tertiary)' }}>No invoices yet</p>
          ) : (
            <div className="divide-y" style={{ borderColor: 'var(--th-border)' }}>
              {recent.map((inv) => {
                const ss = STATUS_STYLES[inv.status] || STATUS_STYLES.received;
                return (
                  <div
                    key={inv.id}
                    className="flex items-center gap-3 px-5 py-3 cursor-pointer transition-colors hover:bg-[var(--th-hover)]"
                    onClick={() => navigate('/invoices')}
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate" style={{ color: 'var(--th-text-primary)' }}>
                        {inv.vendor_name || 'Unknown Vendor'}
                      </p>
                      <p className="text-xs truncate" style={{ color: 'var(--th-text-tertiary)' }}>
                        {inv.billing_period || inv.id} · {fmtDate(inv.due_date)}
                      </p>
                    </div>
                    <span
                      className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize"
                      style={{
                        backgroundColor: ss.bg,
                        color: ss.text,
                        border: `1px solid ${ss.border}`,
                      }}
                    >
                      {inv.status}
                    </span>
                    <span className="text-sm font-semibold whitespace-nowrap" style={{ color: 'var(--th-text-primary)' }}>
                      {currency(inv.outstanding_balance ?? 0)}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Monthly Spend Trend */}
      <div className="rounded-lg p-5" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold flex items-center gap-2" style={{ color: 'var(--th-text-primary)' }}>
            <TrendingUp className="h-4 w-4" style={{ color: 'var(--th-accent)' }} />
            Monthly Spend Trend
          </h2>
        </div>
        {monthly.length === 0 ? (
          <p className="py-6 text-center text-sm" style={{ color: 'var(--th-text-tertiary)' }}>No data for the last 12 months</p>
        ) : (
          <div className="overflow-x-auto">
            <div className="flex items-end gap-2 min-w-[400px]" style={{ height: '160px' }}>
              {(() => {
                const maxCharge = Math.max(...monthly.map(m => m.total_charges), 1);
                return monthly.map((m) => {
                  const pct = (m.total_charges / maxCharge) * 100;
                  const isCurrent = m.month === monthly[monthly.length - 1]?.month;
                  return (
                    <div key={m.month} className="flex-1 flex flex-col items-center gap-1" title={`${m.month}: ${currency(m.total_charges)}`}>
                      <div
                        className="w-full rounded-t"
                        style={{
                          height: `${Math.max(pct, 4)}%`,
                          backgroundColor: isCurrent ? 'var(--th-accent)' : 'var(--th-accent-muted)',
                          opacity: 0.7,
                        }}
                      />
                      <span className="text-[10px] whitespace-nowrap" style={{ color: 'var(--th-text-quaternary)' }}>
                        {m.month?.slice(-2) === m.month?.slice(0, 2) ? m.month : m.month?.slice(5)}
                      </span>
                    </div>
                  );
                });
              })()}
            </div>
          </div>
        )}
      </div>

      {/* Quick Links to Vendors */}
      <div className="rounded-lg p-5" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold flex items-center gap-2" style={{ color: 'var(--th-text-primary)' }}>
            <Building2 className="h-4 w-4" style={{ color: 'var(--th-accent)' }} />
            Vendors
          </h2>
          <button
            onClick={() => navigate('/vendors')}
            className="text-xs font-medium flex items-center gap-1"
            style={{ color: 'var(--th-accent)' }}
          >
            View all <ChevronRight className="h-3 w-3" />
          </button>
        </div>
        <div className="flex flex-wrap gap-2">
          {vendors.slice(0, 10).map((v) => (
            <button
              key={v.id}
              onClick={() => navigate(`/vendors/${v.id}`)}
              className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors"
              style={{
                backgroundColor: 'var(--th-hover)',
                color: 'var(--th-text-secondary)',
                border: '1px solid var(--th-border-strong)',
              }}
            >
              <Building2 className="h-3 w-3" />
              {v.name}
              <ArrowUpRight className="h-3 w-3" style={{ color: 'var(--th-accent)' }} />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function SummaryCard({ icon, iconBg, iconColor, label, value }: {
  icon: React.ReactNode;
  iconBg: string;
  iconColor: string;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-lg p-4" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}>
      <div className="flex items-center gap-3">
        <div
          className="flex h-10 w-10 items-center justify-center rounded-lg"
          style={{ backgroundColor: iconBg, color: iconColor }}
        >
          {icon}
        </div>
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-wider" style={{ color: 'var(--th-text-tertiary)' }}>{label}</p>
          <p className="text-base font-bold mt-0.5" style={{ color: 'var(--th-text-primary)' }}>{value}</p>
        </div>
      </div>
    </div>
  );
}