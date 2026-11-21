type NativeError = {domain:string;code:number;hostname?:string};
const stages = ['google-authorization-or-token-exchange','firebase-credential-exchange','firebase-authentication','google-sign-in','email-sign-in','email-registration','golfer-profile'] as const;
export type AuthStage = typeof stages[number];
function record(value:unknown):Record<string,unknown> {return value && typeof value === 'object' ? value as Record<string,unknown> : {};}
function identifier(value:unknown) {return typeof value === 'string' && /^[a-zA-Z0-9_.\/-]{1,100}$/.test(value) ? value : undefined;}
export function authDiagnostics(error:unknown,fallback:AuthStage) {
  const value=record(error), data=record(value.data);
  // Capacitor exposes reject data on error.data. No raw message/URL is logged.
  const stage=stages.includes(data.stage as AuthStage) ? data.stage as AuthStage : fallback;
  const nativeErrors:NativeError[]=[];
  for(const item of Array.isArray(data.nativeErrors) ? data.nativeErrors.slice(0,12) : []) {
    const row=record(item),domain=identifier(row.domain);
    if (!domain || typeof row.code !== 'number' || !Number.isSafeInteger(row.code)) continue;
    const hostname=typeof row.hostname === 'string' && /^(?:[a-z0-9-]+\.)+[a-z0-9-]+$/i.test(row.hostname) && row.hostname.length <= 253 ? row.hostname : undefined;
    nativeErrors.push({domain,code:row.code,...(hostname ? {hostname} : {})});
  }
  return {stage,code:identifier(value.code) ?? 'unknown',nativeErrors,
    authenticated:typeof data.authenticated === 'boolean' ? data.authenticated : null};
}
export function authFailure(error:unknown,fallback:AuthStage) {
  const diagnostic=authDiagnostics(error,fallback);
  const name=diagnostic.stage.startsWith('google-') ? 'Google sign-in (authorization/token/profile)' : diagnostic.stage === 'golfer-profile' ? 'Golfer profile creation' : 'Firebase authentication';
  const code=diagnostic.code.replace(/^auth\//,'');
  const dns=diagnostic.nativeErrors.some(item => item.domain === 'NSURLErrorDomain' && item.code === -1003);
  const network=dns || code === 'network-request-failed' || diagnostic.nativeErrors.some(item => item.domain === 'NSURLErrorDomain' && [-1001,-1004,-1005,-1009].includes(item.code));
  const host=diagnostic.nativeErrors.find(item => item.hostname)?.hostname;
  const messages:Record<string,string>={
    'invalid-credential':'The sign-in credentials were not accepted.',
    'wrong-password':'The email or password was not accepted.',
    'invalid-email':'Enter a valid email address.',
    'email-already-in-use':'An account already uses this email. Sign in to that account.',
    'account-exists-with-different-credential':'An account already uses this email with another sign-in method. Use that method to sign in.',
    'weak-password':'Choose a stronger password.',
    'too-many-requests':'Too many attempts. Wait a moment before trying again.',
    'user-disabled':'This account is disabled.',
    'popup-closed-by-user':'Sign-in was cancelled.',
  };
  const cancelled=diagnostic.nativeErrors.some(item => item.domain === 'com.google.GIDSignIn' && item.code === -5);
  const reason=cancelled ? 'Sign-in was cancelled.' : dns ? `Could not resolve ${host ?? 'a service hostname (not supplied by iOS)'}.` : network ? `The network request failed${host ? ` for ${host}` : ''}.` : messages[code] ?? `The request failed (${diagnostic.code}).`;
  const advice=network ? ' Try another internet connection and check any VPN or DNS filtering, then retry. Offline practice is still available.' : '';
  const state=diagnostic.authenticated === true ? ' A Firebase account remains signed in.' : '';
  return new Error(`${name}: ${reason}${advice}${state}`);
}
