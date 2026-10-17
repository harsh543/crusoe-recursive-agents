-- Pin search_path on the retrieval functions (Supabase advisor 0011_function_search_path_mutable).
alter function public.search_grounding(text, boolean, int) set search_path = public, pg_catalog;
alter function public.search_policy_chunks(text, text[], text, text, int) set search_path = public, pg_catalog;
