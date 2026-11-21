import { converted, type Shot, type Units } from '../../src/domain.ts';

export function shotCue(shot: Shot, units: Units) {
  if (shot.record_kind !== 'real' || shot.processing_state !== 'final') return '';
  if (shot.carry_yards !== null) return 'Modeled carry, ' +
    Math.round(converted(shot.carry_yards,'carry_yards',units)) + (units === 'metric' ? ' meters.' : ' yards.');
  if (shot.ball_speed_mph !== null) return 'Ball speed, ' +
    Math.round(converted(shot.ball_speed_mph,'ball_speed_mph',units)) + (units === 'metric' ? ' kilometers per hour.' : ' miles per hour.');
  return 'Shot recorded.';
}

export function speechAvailable() {
  return typeof speechSynthesis !== 'undefined' && typeof SpeechSynthesisUtterance !== 'undefined';
}
export function stopSpeaking() {
  if (speechAvailable()) speechSynthesis.cancel();
}
export function speakCue(message:string, failed:() => void) {
  if (!message || !speechAvailable()) return;
  const speech = new SpeechSynthesisUtterance(message);
  const voices = speechSynthesis.getVoices();
  const voice = voices.find(v => v.localService && v.lang.startsWith('en'));
  if (voices.length && !voice) { failed(); return; }
  if (voice) speech.voice = voice;
  speech.lang = voice?.lang ?? 'en-US';
  speech.onerror = e => { if (e.error !== 'interrupted' && e.error !== 'canceled') failed(); };
  // Drop stale announcements if a fresher monitor event arrives.
  speechSynthesis.cancel();
  speechSynthesis.speak(speech);
}
