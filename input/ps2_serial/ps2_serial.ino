#include <PS2X_lib.h>  // v1.6

// PS2 pins (adjust if you wire differently)
#define PS2_DAT 13
#define PS2_CMD 12
#define PS2_SEL 11
#define PS2_CLK 10

// Features
#define pressures false
#define rumble false

const unsigned long REINIT_MS = 2000;  // retry connect interval
const uint8_t STICK_DEADZONE = 1;      // ignore tiny stick jitter

struct ButtonDef {
  uint16_t mask;
  const char* name;
};

const ButtonDef BUTTONS[] = {
    {PSB_START, "START"},   {PSB_SELECT, "SELECT"}, {PSB_PAD_UP, "UP"},
    {PSB_PAD_DOWN, "DOWN"}, {PSB_PAD_LEFT, "LEFT"}, {PSB_PAD_RIGHT, "RIGHT"},
    {PSB_L1, "L1"},         {PSB_R1, "R1"},         {PSB_L2, "L2"},
    {PSB_R2, "R2"},         {PSB_L3, "L3"},         {PSB_R3, "R3"},
    {PSB_CROSS, "CROSS"},   {PSB_CIRCLE, "CIRCLE"}, {PSB_SQUARE, "SQUARE"},
    {PSB_TRIANGLE, "TRIANGLE"},
};

PS2X ps2x;

int error = 0;
byte type = 0;
byte vibrate = 0;

int lastLX = -1, lastLY = -1, lastRX = -1, lastRY = -1;
uint16_t lastButtons = 0;
unsigned long lastAttempt = 0;

struct AxisCal {
  int center;
  int minSeen;
  int maxSeen;
};

AxisCal calLX = {128, 255, 0};
AxisCal calLY = {128, 255, 0};
AxisCal calRX = {128, 255, 0};
AxisCal calRY = {128, 255, 0};

bool configureController() {
  error = ps2x.config_gamepad(PS2_CLK, PS2_CMD, PS2_SEL, PS2_DAT, pressures,
                              rumble);
  if (error != 0) {
    Serial.print("ps2_error=");
    Serial.println(error);
    lastAttempt = millis();
    return false;
  }

  type = ps2x.readType();
  Serial.print("ps2_connected type=");
  Serial.println(type);
  lastAttempt = millis();

  // prime calibration with first read
  ps2x.read_gamepad(false, 0);
  calLX.center = ps2x.Analog(PSS_LX);
  calLY.center = ps2x.Analog(PSS_LY);
  calRX.center = ps2x.Analog(PSS_RX);
  calRY.center = ps2x.Analog(PSS_RY);
  calLX.minSeen = calLY.minSeen = calRX.minSeen = calRY.minSeen = 255;
  calLX.maxSeen = calLY.maxSeen = calRX.maxSeen = calRY.maxSeen = 0;

  return true;
}

void printSticks(int lx, int ly, int rx, int ry) {
  Serial.print("sticks LX=");
  Serial.print(lx);
  Serial.print(",LY=");
  Serial.print(ly);
  Serial.print(",RX=");
  Serial.print(rx);
  Serial.print(",RY=");
  Serial.println(ry);
}

void printButtons(uint16_t state) {
  Serial.print("buttons ");
  const size_t count = sizeof(BUTTONS) / sizeof(BUTTONS[0]);
  for (size_t i = 0; i < count; i++) {
    const ButtonDef def = BUTTONS[i];
    Serial.print(def.name);
    Serial.print("=");
    Serial.print((state & def.mask) ? 1 : 0);
    if (i + 1 < count) {
      Serial.print(",");
    }
  }
  Serial.println();
}

int normalizeAxis(int raw, AxisCal& cal) {
  if (raw < cal.minSeen) cal.minSeen = raw;
  if (raw > cal.maxSeen) cal.maxSeen = raw;

  const int delta = raw - cal.center;
  const int posRange = max(1, cal.maxSeen - cal.center);
  const int negRange = max(1, cal.center - cal.minSeen);
  const int range = delta >= 0 ? posRange : negRange;
  long scaled = (long)delta * 127 / range;
  if (scaled > 127) scaled = 127;
  if (scaled < -127) scaled = -127;
  return (int)scaled;
}

void recalibrateCenters() {
  calLX.center = ps2x.Analog(PSS_LX);
  calLY.center = ps2x.Analog(PSS_LY);
  calRX.center = ps2x.Analog(PSS_RX);
  calRY.center = ps2x.Analog(PSS_RY);
  calLX.minSeen = calLY.minSeen = calRX.minSeen = calRY.minSeen = 255;
  calLX.maxSeen = calLY.maxSeen = calRX.maxSeen = calRY.maxSeen = 0;
  Serial.println("calibrated_sticks");
}

void setup() {
  Serial.begin(115200);
  delay(300);  // allow wireless receivers to boot
  configureController();
}

void loop() {
  if (error != 0) {
    if (millis() - lastAttempt >= REINIT_MS) {
      configureController();
    }
    delay(50);
    return;
  }

  ps2x.read_gamepad(false, vibrate);

  uint16_t buttonState = 0;
  const size_t count = sizeof(BUTTONS) / sizeof(BUTTONS[0]);
  for (size_t i = 0; i < count; i++) {
    if (ps2x.Button(BUTTONS[i].mask)) {
      buttonState |= BUTTONS[i].mask;
    }
  }

  if (buttonState != lastButtons) {
    printButtons(buttonState);
    lastButtons = buttonState;
  }

  if ((buttonState & PSB_L3) && (buttonState & PSB_R3)) {
    recalibrateCenters();
  }

  const bool triggerHeld = (buttonState & PSB_L1) || (buttonState & PSB_R1);
  if (triggerHeld) {
    const int lxRaw = ps2x.Analog(PSS_LX);
    const int lyRaw = ps2x.Analog(PSS_LY);
    const int rxRaw = ps2x.Analog(PSS_RX);
    const int ryRaw = ps2x.Analog(PSS_RY);

    const int lx = normalizeAxis(lxRaw, calLX);
    const int ly = normalizeAxis(lyRaw, calLY);
    const int rx = normalizeAxis(rxRaw, calRX);
    const int ry = normalizeAxis(ryRaw, calRY);

    const bool sticksChanged =
        lastLX < 0 || abs(lx - lastLX) > STICK_DEADZONE ||
        abs(ly - lastLY) > STICK_DEADZONE ||
        abs(rx - lastRX) > STICK_DEADZONE ||
        abs(ry - lastRY) > STICK_DEADZONE;
    if (sticksChanged) {
      printSticks(lx, ly, rx, ry);
      lastLX = lx;
      lastLY = ly;
      lastRX = rx;
      lastRY = ry;
    }
  }

  vibrate = ps2x.Analog(PSAB_CROSS);  // map X pressure to rumble speed
  delay(30);
}
