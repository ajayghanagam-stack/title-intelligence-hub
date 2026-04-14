export interface AuthUser {
  id: string;
  email: string;
  full_name: string | null;
}

export interface Org {
  id: string;
  name: string;
  slug: string;
  logo_url: string | null;
}

export interface MicroApp {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  icon?: string | null;
  is_active?: boolean;
  created_at?: string;
}

export interface Subscription {
  id: string;
  app_id: string;
  status: string;
  micro_app: MicroApp | null;
}

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
}

export interface Account {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  user_count: number;
  created_at: string;
}

export interface AccountUser {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
}

export interface AccountSubscription {
  id: string;
  app_id: string;
  app_name: string;
  app_slug: string;
  status: string;
}

export interface AccountDetail {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  created_at: string;
  users: AccountUser[];
  subscriptions: AccountSubscription[];
}

export interface UsageItem {
  name: string;
  filenames?: string[] | null;
  status: string;
  created_at: string;
}

export interface AppUsage {
  app_slug: string;
  app_name: string;
  completed_count: number;
  total_count: number;
  items: UsageItem[];
}

export interface OrgUsage {
  org_id: string;
  org_name: string;
  start_date: string;
  end_date: string;
  apps: AppUsage[];
}
