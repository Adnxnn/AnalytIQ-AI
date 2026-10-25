import {createClient,SupabaseClient} from "@supabase/supabase-js";
let singleton:SupabaseClient|null=null;
export function getSupabase():SupabaseClient|null {
 const url=process.env.NEXT_PUBLIC_SUPABASE_URL;
 const key=process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
 if(!url||!key)return null;
 if(!singleton)singleton=createClient(url,key,{auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:true}});
 return singleton;
}
