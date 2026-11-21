import type { CapacitorConfig } from '@capacitor/cli';

// Bundle ID selected for the requested new MODUS Golf Apple registration.
const config: CapacitorConfig = {
  appId: 'com.modusgolf.app', appName: 'MODUS Golf', webDir: 'dist',
  // Capacitor bridge debug logs can include OAuth results. Use only sanitized
  // MODUS Auth diagnostics from the native plugin and account wrapper.
  loggingBehavior: 'none',
  plugins: {FirebaseAuthentication:{skipNativeAuth:false,providers:['google.com']}},
  experimental:{ios:{spm:{swiftToolsVersion:'6.1',
    packageOptions:{'@capacitor-firebase/authentication':{symlink:true}},
    packageTraits:{'@capacitor-firebase/authentication':['Google']}}}}
};
// Deliberately no server.url: release assets must ship inside the iPhone app.
export default config;
