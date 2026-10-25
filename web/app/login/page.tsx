"use client";
import {FormEvent,useState} from "react";
import Link from "next/link";
import {useRouter} from "next/navigation";
import {getSupabase} from "../../lib/supabase";
export default function Login(){
 const [email,setEmail]=useState("");const [password,setPassword]=useState("");
 const [mode,setMode]=useState<"password"|"signup"|"magic"|"reset">("password");
 const [busy,setBusy]=useState(false);const [message,setMessage]=useState("");
 const router=useRouter();
 async function submit(e:FormEvent){e.preventDefault();const sb=getSupabase();if(!sb){setMessage("Authentication is not configured yet. Contact the workspace administrator.");return}
 setBusy(true);setMessage("");
 try{
 let error:Error|null=null;
 if(mode==="password"){({error}=await sb.auth.signInWithPassword({email,password}));}
 if(mode==="signup"){({error}=await sb.auth.signUp({email,password}));}
 if(mode==="magic"){({error}=await sb.auth.signInWithOtp({email,options:{emailRedirectTo:location.origin+"/"}}));}
 if(mode==="reset"){({error}=await sb.auth.resetPasswordForEmail(email,{redirectTo:location.origin+"/login"}));}
 if(error)throw error;
 if(mode==="password")router.push("/");
 else setMessage(mode==="signup"?"Check your email to confirm your account.":mode==="reset"?"Check your email for a reset link.":"Check your email for your sign-in link.");
 }catch(e){setMessage(e instanceof Error?e.message:"Authentication failed")}finally{setBusy(false)}
 }
 return <main className="auth-shell"><div className="auth-brand"><Link href="/">◈ Analyt<span>IQ</span> AI</Link><small>SECURE ANALYTICS WORKSPACE</small></div><section className="auth-card"><div className="eyebrow">WELCOME TO YOUR WORKSPACE</div><h1>{mode==="signup"?"Create an account":mode==="reset"?"Reset your password":mode==="magic"?"Email sign-in":"Welcome back"}</h1><p>Private projects, verified calculations and reproducible insights.</p><form onSubmit={submit}><label>Email address<input type="email" autoComplete="email" required value={email} onChange={e=>setEmail(e.target.value)} placeholder="you@company.com"/></label>{(mode==="password"||mode==="signup")&&<label>Password<input type="password" minLength={6} required value={password} onChange={e=>setPassword(e.target.value)} placeholder="Enter password"/></label>}<button className="btn" disabled={busy}>{busy?"Please wait...":mode==="signup"?"Create account":mode==="reset"?"Send reset link":mode==="magic"?"Send magic link":"Sign in"}</button></form>{message&&<p role="status" className="auth-feedback">{message}</p>}<div className="auth-switch"><button onClick={()=>setMode("password")}>Password sign-in</button><button onClick={()=>setMode("signup")}>Register</button><button onClick={()=>setMode("magic")}>Magic link</button><button onClick={()=>setMode("reset")}>Forgot password?</button></div></section></main>
}
