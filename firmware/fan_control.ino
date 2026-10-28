// ATmega168/328P (Arduino Pro / Pro Mini 互換) 想定
// D3 = OC2B (Timer2) を使い、PCファン規格の約25kHzでPWM出力する
//
// シリアルコマンド (9600bps, 改行区切り):
//   0〜100 の整数  : ファンのデューティ比[%]を設定 (例: "50")
//   "?"           : 現在のデューティ比を返す
// 有効なコマンドを10秒間受信しなかった場合、安全のためデューティ比を100%にする
const int FAN_PWM_PIN = 3;
const unsigned long PWM_FREQ_HZ = 25000;
// 高速PWM(モード7)、分周比8: f = F_CPU / (8 * (TOP + 1))
const uint8_t PWM_TOP = F_CPU / 8 / PWM_FREQ_HZ - 1;  // 16MHz:79, 8MHz:39

const unsigned long BAUD_RATE = 9600;
const unsigned long COMMAND_TIMEOUT_MS = 10000;
const int FAILSAFE_DUTY = 100;

int currentDuty = FAILSAFE_DUTY;
unsigned long lastCommandMs = 0;

void setupFanPwm() {
  pinMode(FAN_PWM_PIN, OUTPUT);
  TCCR2A = _BV(COM2B1) | _BV(WGM21) | _BV(WGM20);  // OC2B非反転, 高速PWM
  TCCR2B = _BV(WGM22) | _BV(CS21);                 // TOP=OCR2A, 分周比8
  OCR2A = PWM_TOP;
}

// NPNトランジスタ経由でファンのPWM線をGNDに落とす回路のため、Dutyは反転して出力する
void setFanDuty(int percent) {
  percent = constrain(percent, 0, 100);
  currentDuty = percent;
  int inverted = 100 - percent;
  OCR2B = (uint16_t)PWM_TOP * inverted / 100;
}

// 1行分のコマンドを処理する。有効なコマンドならtrueを返す
bool handleCommand(const char *line) {
  if (line[0] == '?' && line[1] == '\0') {
    Serial.print(F("DUTY "));
    Serial.println(currentDuty);
    return true;
  }

  // 数字のみ(1〜3桁)を受け付ける
  int len = 0;
  int value = 0;
  for (; line[len] != '\0'; len++) {
    if (line[len] < '0' || line[len] > '9' || len >= 3) {
      Serial.println(F("ERR"));
      return false;
    }
    value = value * 10 + (line[len] - '0');
  }
  if (len == 0 || value > 100) {
    Serial.println(F("ERR"));
    return false;
  }

  setFanDuty(value);
  Serial.print(F("OK "));
  Serial.println(value);
  return true;
}

void setup() {
  setupFanPwm();
  setFanDuty(FAILSAFE_DUTY);  // 起動直後は安全のため最大
  Serial.begin(BAUD_RATE);
  lastCommandMs = millis();
}

void loop() {
  static char buf[8];
  static uint8_t pos = 0;
  static bool overflow = false;

  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (overflow) {
        Serial.println(F("ERR"));
      } else if (pos > 0) {
        buf[pos] = '\0';
        if (handleCommand(buf)) {
          lastCommandMs = millis();
        }
      }
      pos = 0;
      overflow = false;
    } else if (pos < sizeof(buf) - 1) {
      buf[pos++] = c;
    } else {
      overflow = true;
    }
  }

  // フェイルセーブ: コマンドが途絶えたら最大にする
  if (currentDuty != FAILSAFE_DUTY && millis() - lastCommandMs >= COMMAND_TIMEOUT_MS) {
    setFanDuty(FAILSAFE_DUTY);
    Serial.println(F("TIMEOUT 100"));
  }
}
