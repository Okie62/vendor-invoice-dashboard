import axios from 'axios';

// ── Types ──
export interface User {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  is_admin: boolean;
  created_at?: string;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user?: User;
}

export interface Vendor {
  id: number;
  name: string;
  email_domain: string;
}

export interface InvoiceSummary {
  previous_balance: number;
  credit_card_surcharges: number;
  payment_received: number;
  new_charges: number;
  outstanding_balance: number;
}

export interface Customer {
  id?: number;
  invoice_id?: string;
  name: string;
  account_id: string;
  partner_id: string;
  total: number;
}

export interface LineItem {
  id?: number;
  invoice_id?: string;
  customer_name: string;
  date: string;
  item: string;
  type: string;
  qty: number;
  unit_price: number;
  amount: number;
}

export interface Invoice {
  id: string;
  vendor: string;
  billing_period: string;
  invoice_date?: string;
  is_credit_memo: boolean;
  references_invoice: string | null;
  partner_name: string;
  partner_id: string;
  partner_username: string;
  summary: InvoiceSummary;
  customers: Customer[];
  line_items: LineItem[];
  pdf_path?: string;
  created_at?: string;
}

export interface InvoiceBulkResponse {
  invoices: Invoice[];
}

export interface DBSummary {
  prev: number;
  cc: number;
  pay: number;
  new: number;
  outstanding: number;
  count: number;
}

export interface InvoiceFilters {
  vendor?: string;
  start?: string;
  end?: string;
  search?: string;
}

export interface UserCreateRequest {
  email: string;
  password: string;
  full_name: string;
}

export interface AdminUser {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  is_admin: boolean;
  created_at: string;
}

export interface ReviewItem {
  id: string;
  invoice_id: string;
  vendor: string;
  status: string;
  extracted_text: string;
  confidence: number;
  parsed_data: Record<string, unknown>;
  created_at: string;
}

export interface FormatDef {
  id: string;
  vendor: string;
  name: string;
  version: string;
  fields: string[];
}

// ── Axios instance ──
const api = axios.create({ baseURL: '' });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

let refreshInFlight: Promise<string | null> | null = null;

async function performRefresh(): Promise<string | null> {
  const refreshToken = localStorage.getItem('refresh_token');
  if (!refreshToken) return null;
  try {
    const { data } = await axios.post<AuthResponse>('/api/auth/refresh', { refresh_token: refreshToken });
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    return data.access_token;
  } catch {
    return null;
  }
}

function redirectToLogin() {
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  if (window.location.pathname !== '/login') window.location.href = '/login';
}

api.interceptors.response.use(
  (res) => res,
  async (err) => {
    const status = err?.response?.status;
    const original = err?.config;
    const url: string = original?.url || '';
    const isAuthEp = url.includes('/api/auth/login') || url.includes('/api/auth/refresh');
    if (status === 401 && original && !original._retry && !isAuthEp) {
      original._retry = true;
      if (!refreshInFlight) refreshInFlight = performRefresh().finally(() => { refreshInFlight = null; });
      const newToken = await refreshInFlight;
      if (newToken) {
        original.headers = original.headers || {};
        original.headers.Authorization = `Bearer ${newToken}`;
        return api(original);
      }
      redirectToLogin();
      return new Promise(() => {});
    }
    const detail = err?.response?.data?.detail || err?.response?.data?.error;
    if (typeof detail === 'string') err.message = detail;
    return Promise.reject(err);
  },
);

// ── Auth ──
export async function login(email: string, password: string): Promise<AuthResponse> {
  const { data } = await api.post<AuthResponse>('/api/auth/login', { email, password });
  return data;
}

export async function register(email: string, password: string, full_name: string): Promise<AuthResponse> {
  const { data } = await api.post<AuthResponse>('/api/auth/register', { email, password, full_name });
  return data;
}

export async function getCurrentUser(): Promise<User> {
  const { data } = await api.get<User>('/api/auth/me');
  return data;
}

export async function checkSetup(): Promise<{ has_users: boolean }> {
  const { data } = await api.get<{ has_users: boolean }>('/api/auth/setup-check');
  return data;
}

// ── Vendors ──
export async function getVendors(): Promise<Vendor[]> {
  const { data } = await api.get<Vendor[]>('/api/vendors');
  return data;
}

// ── Invoices ──
export async function getInvoices(filters: InvoiceFilters = {}): Promise<Invoice[]> {
  const params: Record<string, string> = {};
  if (filters.vendor) params.vendor = filters.vendor;
  if (filters.start) params.start = filters.start;
  if (filters.end) params.end = filters.end;
  if (filters.search) params.search = filters.search;
  const { data } = await api.get<Invoice[]>('/api/invoices', { params });
  return data;
}

export async function getInvoicesBulk(filters: InvoiceFilters = {}): Promise<InvoiceBulkResponse> {
  const params: Record<string, string> = {};
  if (filters.vendor) params.vendor = filters.vendor;
  if (filters.start) params.start = filters.start;
  if (filters.end) params.end = filters.end;
  if (filters.search) params.search = filters.search;
  const { data } = await api.get<InvoiceBulkResponse>('/api/invoices/bulk', { params });
  return data;
}

export async function getInvoice(id: string) {
  const { data } = await api.get(`/api/invoices/${id}`);
  return data;
}

export async function deleteInvoice(id: string): Promise<{ success: boolean }> {
  const { data } = await api.delete<{ success: boolean }>(`/api/invoices/${id}`);
  return data;
}

export async function updateInvoice(id: string, payload: { invoice?: Record<string, unknown>; customers?: Record<string, unknown>[]; line_items?: Record<string, unknown>[] }) {
  const { data } = await api.put(`/api/invoices/${id}`, payload);
  return data;
}

export async function getInvoiceRawText(id: string): Promise<{ text: string }> {
  const { data } = await api.get<{ text: string }>(`/api/invoices/${id}/raw-text`);
  return data;
}

// ── Summary ──
export async function getSummary(filters: InvoiceFilters = {}): Promise<DBSummary> {
  const params: Record<string, string> = {};
  if (filters.vendor) params.vendor = filters.vendor;
  if (filters.start) params.start = filters.start;
  if (filters.end) params.end = filters.end;
  const { data } = await api.get<DBSummary>('/api/summary', { params });
  return data;
}

// ── Upload ──
export async function uploadInvoice(file: File, vendor: string): Promise<{ success: boolean; invoice_id: string }> {
  const form = new FormData();
  form.append('file', file);
  form.append('vendor', vendor);
  const { data } = await api.post<{ success: boolean; invoice_id: string }>('/api/upload', form);
  return data;
}

// ── Poll ──
export async function triggerPoll(reprocess = false): Promise<{ success: boolean; processed: number }> {
  const { data } = await api.post<{ success: boolean; processed: number }>(`/api/poll${reprocess ? '?reprocess=true' : ''}`);
  return data;
}

// ── CSV Export ──
export function getExportUrl(type: 'invoices' | 'customers' | 'line-items'): string {
  const token = localStorage.getItem('access_token');
  return `/api/export/${type}?token=${token}`;
}

// ── Admin Users ──
export async function getAdminUsers(): Promise<AdminUser[]> {
  const { data } = await api.get<AdminUser[]>('/api/admin/users');
  return data;
}

export async function createAdminUser(body: UserCreateRequest): Promise<AdminUser> {
  const { data } = await api.post<AdminUser>('/api/admin/users', body);
  return data;
}

export async function toggleAdminRole(userId: number, is_admin: boolean): Promise<{ success: boolean }> {
  const { data } = await api.patch<{ success: boolean }>(`/api/admin/users/${userId}/role`, { is_admin });
  return data;
}

export async function deactivateUser(userId: number): Promise<{ success: boolean }> {
  const { data } = await api.delete<{ success: boolean }>(`/api/admin/users/${userId}`);
  return data;
}

// ── Format Review (stub endpoints — may 404 until backend is ready) ──
export async function getReviews(status = 'pending'): Promise<ReviewItem[]> {
  const { data } = await api.get<ReviewItem[]>('/api/reviews', { params: { status } });
  return data;
}

export async function getReview(id: string): Promise<ReviewItem> {
  const { data } = await api.get<ReviewItem>(`/api/reviews/${id}`);
  return data;
}

export async function patchReview(id: string, body: Partial<ReviewItem>): Promise<ReviewItem> {
  const { data } = await api.patch<ReviewItem>(`/api/reviews/${id}`, body);
  return data;
}

export async function extractReview(id: string, field_overrides: Record<string, unknown> = {}): Promise<ReviewItem> {
  const { data } = await api.post<ReviewItem>(`/api/reviews/${id}/extract`, { field_overrides });
  return data;
}

export async function getFormats(): Promise<FormatDef[]> {
  const { data } = await api.get<FormatDef[]>('/api/formats');
  return data;
}