import {test} from 'node:test';
import assert from 'node:assert/strict';
import {authDiagnostics,authFailure} from '../src/auth-diagnostics.ts';

test('native DNS failures retain stage and hostname without exposing request credentials',() => {
  const error={code:'auth/network-request-failed',message:'secret-token',data:{stage:'firebase-credential-exchange',authenticated:false,
    nativeErrors:[{domain:'FIRAuthErrorDomain',code:17020},{domain:'NSURLErrorDomain',code:-1003,hostname:'identitytoolkit.googleapis.com',url:'https://host/?key=secret-token'}],token:'secret-token'}};
  const diagnostic=authDiagnostics(error,'google-sign-in');
  assert.equal(diagnostic.stage,'firebase-credential-exchange');
  assert.equal(diagnostic.authenticated,false);
  assert.equal(diagnostic.nativeErrors[1].hostname,'identitytoolkit.googleapis.com');
  assert.ok(!JSON.stringify(diagnostic).includes('secret-token'));
  assert.match(authFailure(error,'google-sign-in').message,/Firebase authentication: Could not resolve identitytoolkit.googleapis.com/);
});
test('Google failures stay distinct and unavailable hostnames are not guessed',() => {
  const error={data:{stage:'google-authorization-or-token-exchange',nativeErrors:[{domain:'NSURLErrorDomain',code:-1003}]}};
  const message=authFailure(error,'google-sign-in').message;
  assert.match(message,/Google sign-in \(authorization\/token\/profile\)/);
  assert.match(message,/not supplied by iOS/);
  assert.doesNotMatch(message,/googleapis/);
});
test('diagnostic allowlist rejects URLs, unsafe codes and unknown fields',() => {
  const diagnostic=authDiagnostics({code:'https://bad/?token=secret',data:{stage:'secret',authenticated:'true',nativeErrors:[
    {domain:'NSURLErrorDomain',code:-1003,hostname:'https://bad/?token=secret'},
    {domain:'secret with spaces',code:4}, {domain:'NSURLErrorDomain',code:Infinity}
  ]}},'email-sign-in');
  assert.deepEqual(diagnostic,{stage:'email-sign-in',code:'unknown',authenticated:null,nativeErrors:[{domain:'NSURLErrorDomain',code:-1003}]});
  assert.match(authFailure({code:'auth/email-already-in-use'},'email-registration').message,/already uses this email/);
  assert.match(authFailure({code:'auth/network-request-failed'},'email-sign-in').message,/network request failed/);
});
