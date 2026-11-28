import assert from 'node:assert/strict';
import {test} from 'node:test';
import {pathToFileURL} from 'node:url';
import {join} from 'node:path';

const root = process.env.IR_REGISTRATION_TEST_RUNTIME;
assert.ok(root, 'Use the staged registration runtime for calendar tests.');
const {selectedWeekend, parseSeasonText, readRaceWeather, readLicenseRange, scheduleSource} = await import(pathToFileURL(join(root, 'season-catalog.mjs')));
const {includeSpecialEvents} = await import(pathToFileURL(join(root, 'special-events.mjs')));
const {validateChoice} = await import(pathToFileURL(join(root, 'endurance.mjs')));
const week = selectedWeekend('2026-11-27');
const spaName = 'Creventic 992 Endurance Cup';
const spaCar = 'Porsche 911 Cup (992.2)';

test('the published Spa special event has four selectable starts and confirmed 60-minute registration', () => {
  const catalog = includeSpecialEvents({...week, series: []}, null);
  const spa = catalog.series.find(event => event.name === spaName);
  assert.equal(spa.slotDetails.length, 4);
  assert.deepEqual(spa.slots, ['2026-11-27T17:00', '2026-11-28T02:00', '2026-11-28T07:00', '2026-11-28T11:00']);
  const first = spa.slotDetails[0];
  assert.equal(first.registrationOpenUtc, '2026-11-27T21:00:00.000Z');
  assert.equal(first.registrationKind, 'confirmed');
  validateChoice({series: spaName, car: spaCar, localStart: first.localStart, startUtc: first.startUtc}, catalog);
  assert.throws(() => validateChoice({series: spaName, localStart: first.localStart, startUtc: spa.slotDetails[1].startUtc}, catalog));
  assert.equal(includeSpecialEvents({...selectedWeekend('2026-12-04'), series: []}, null).series.length, 0);
});

test('the official PDF schedule supplies explicit race and pre-session rain chances', () => {
  const pdf = `2026 Creventic 992 Endurance Cup
Porsche 911 Cup (992.2)
Class D 4.0 --> Pro/WC 4.0, Team racing
Friday at 22 GMT, Saturday at 7, 12, and 16 GMT
Min entries for official: 6 | Split at: 60 | Drops: 0
Week 1 (2026-11-27)   Circuit de Spa-Francorchamps - Endurance
(2026-05-16 10:00 1x)   66°F/19°C, Rain chance 57% (8%
before session), Rolling start, Min 2 drivers, Max 16 drivers, Declare drivers.
720
mins`;
  const catalog = includeSpecialEvents(parseSeasonText(pdf, week), null);
  const [spa] = catalog.series;
  assert.equal(catalog.series.length, 1);
  assert.equal(spa.name, spaName);
  assert.equal(spa.slotDetails.length, 4);
  assert.equal(spa.weather.rainChance, 57);
  assert.equal(spa.weather.beforeChance, 8);
  assert.equal(spa.weather.kind, 'forecast');
  assert.equal(spa.slotDetails[3].registrationKind, 'confirmed');
  assert.deepEqual(spa.licenseRequirement, {minimum:'Class D 4.0',maximum:'Pro/WC 4.0',source:scheduleSource});
});

test('reads only a published license range and preserves bounded or rookie eligibility', () => {
  assert.deepEqual(readLicenseRange('GT4\n Class C  4.0 -->\n Class B 4.0, Team racing'),
    {minimum:'Class C 4.0',maximum:'Class B 4.0',source:scheduleSource});
  assert.deepEqual(readLicenseRange('Rookie 4.0 --> Pro/WC 4.0'),
    {minimum:'Rookie 4.0',maximum:'Pro/WC 4.0',source:scheduleSource});
  assert.equal(readLicenseRange('Class C 4.0, team racing'),null);
  assert.equal(readLicenseRange('Class D 4.0 --> Pro/WC 4.0\nClass C 4.0 --> Pro/WC 4.0'),null);
});

test('dry, unknown, and possible pre-session rain remain distinct', () => {
  assert.equal(readRaceWeather('All dry events, Rolling start').kind, 'dry');
  assert.equal(readRaceWeather('Rain chance None').rainChance, 0);
  assert.equal(readRaceWeather('Rain chance 0% (9% before session)').beforeChance, 9);
  assert.equal(readRaceWeather('No evidence, 20°C').kind, 'unknown');
  assert.equal(readRaceWeather('Rain chance 150%').kind, 'unknown');
});
