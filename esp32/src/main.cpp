/*
 * =============================================================================
 * Unified Biometric & Stress Monitor — ESP32 USB Serial Version
 * Sensors: MPU6050, MAX30102, TMP117, GSR, ST7789 TFT
 * =============================================================================
 */

#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <SPI.h>
#include <Wire.h>
#include <MPU6050_tockn.h>
#include "MAX30105.h"
#include "heartRate.h"

// =============================================================================
//  PIN DEFINITIONS
// =============================================================================
#define TFT_CS    15
#define TFT_DC    32
#define TFT_RST   33
#define GSR_CS    27

#define I2C_SDA   21
#define I2C_SCL   22
#define MAX_INT   17

// =============================================================================
//  SENSOR CONSTANTS & GLOBALS
// =============================================================================
Adafruit_ST7789 tft = Adafruit_ST7789(TFT_CS, TFT_DC, TFT_RST);
MPU6050 mpu6050(Wire);
MAX30105 particleSensor;

struct SensorDataPacket {
  uint16_t hr, hrv, spo2, temp, gsr_stress;
  int16_t accX, accY, accZ;
} myData;

// Fake BLE status for UI only
bool bleConnected = false;
bool prevConnected = false;

float baselineRes = 0, sensitivity = 150.0;
float smoothStress = 0, smoothMotion = 0;
float lastAccX, lastAccY, lastAccZ;
unsigned long lastMaxTime = 0;
float currentRes = 0;

#define TMP117_ADDR 0x48
#define TMP117_REG_TEMP 0x00
float skinTempC = 0.0;
float skinTempF = 0.0;
bool tmp117Found = false;

#define RATE_SIZE 4
#define SPO2_BUF_SIZE 100
#define MAX_RR_INTERVALS 20

byte rates[RATE_SIZE];
byte rateSpot = 0;
long lastBeat = 0;
float beatsPerMinute = 0;
int beatAvg = 0;
bool fingerDetected = false;

uint32_t irBuffer[SPO2_BUF_SIZE], redBuffer[SPO2_BUF_SIZE];
int spo2BufIndex = 0;
bool spo2BufFull = false;
float spo2Value = 0.0;

float rrIntervals[MAX_RR_INTERVALS];
int rrIndex = 0, rrCount = 0;
float hrvRMSSD = 0.0;

unsigned long lastTftUpdate = 0;
unsigned long lastSerialReport = 0;

// =============================================================================
//  COLOR PALETTE (ST7789 16-bit RGB565)
// =============================================================================
#define C_BG        0x0841
#define C_SURFACE   0x0861
#define C_DIV       0x2104
#define C_LABEL     0x52AA

#define C_HR        0xF9CB
#define C_HR_DIM    0x8904
#define C_SPO2      0x1E5F
#define C_SPO2_DIM  0x0291
#define C_STRESS    0x1AEE
#define C_STRESS_MID 0xFEC0
#define C_STRESS_HI  0xF800
#define C_HRV       0xA55F
#define C_HRV_DIM   0x4A1C
#define C_TEMP      0xFDC4
#define C_TEMP_DIM  0x7940
#define C_MOTION    0xFCA0
#define C_BLE       0x0E93

float getResistance() {
  SPI.beginTransaction(SPISettings(1000000, MSBFIRST, SPI_MODE0));
  digitalWrite(GSR_CS, LOW);
  int raw = (SPI.transfer(0x00) << 8) | SPI.transfer(0x00);
  digitalWrite(GSR_CS, HIGH);
  SPI.endTransaction();
  if (raw <= 10) return baselineRes;
  return ((1024.0 + 2.0 * raw) * 10.0) / 512.0;
}

void calculateStress(float res) {
  float gsrRaw = constrain((baselineRes - res) / sensitivity, 0.0, 1.0);
  if (gsrRaw >= 0.99) {
    if (millis() - lastMaxTime > 2000) baselineRes = res + (sensitivity * 0.2);
  } else {
    lastMaxTime = millis();
  }

  float deltaX = mpu6050.getAccX() - lastAccX;
  float deltaY = mpu6050.getAccY() - lastAccY;
  float deltaZ = mpu6050.getAccZ() - lastAccZ;
  float rawMotion = constrain(sqrt(deltaX*deltaX + deltaY*deltaY + deltaZ*deltaZ) * 3.0, 0.0, 1.0);

  smoothMotion = (rawMotion * 0.2) + (smoothMotion * 0.8);
  lastAccX = mpu6050.getAccX();
  lastAccY = mpu6050.getAccY();
  lastAccZ = mpu6050.getAccZ();

  float combined = (gsrRaw * 0.7) + (smoothMotion * 0.3);
  smoothStress = (combined * 0.1) + (smoothStress * 0.9);
}

void updateHRV(float newRR_ms) {
  rrIntervals[rrIndex] = newRR_ms;
  rrIndex = (rrIndex + 1) % MAX_RR_INTERVALS;
  if (rrCount < MAX_RR_INTERVALS) rrCount++;
  if (rrCount < 2) {
    hrvRMSSD = 0.0;
    return;
  }

  float sumSq = 0.0;
  int numDiffs = 0;
  for (int i = 1; i < rrCount; i++) {
    int idx_prev = (rrIndex - rrCount + i - 1 + MAX_RR_INTERVALS) % MAX_RR_INTERVALS;
    int idx_curr = (rrIndex - rrCount + i + MAX_RR_INTERVALS) % MAX_RR_INTERVALS;
    float diff = rrIntervals[idx_curr] - rrIntervals[idx_prev];
    sumSq += diff * diff;
    numDiffs++;
  }
  hrvRMSSD = sqrt(sumSq / numDiffs);
}

float calculateSpO2() {
  if (!spo2BufFull) return 0.0;
  float dcRed = 0, dcIR = 0;
  for (int i = 0; i < SPO2_BUF_SIZE; i++) {
    dcRed += redBuffer[i];
    dcIR += irBuffer[i];
  }
  dcRed /= SPO2_BUF_SIZE;
  dcIR /= SPO2_BUF_SIZE;

  float acRedSum = 0, acIRSum = 0;
  for (int i = 0; i < SPO2_BUF_SIZE; i++) {
    float diffR = (float)redBuffer[i] - dcRed;
    float diffI = (float)irBuffer[i] - dcIR;
    acRedSum += diffR * diffR;
    acIRSum += diffI * diffI;
  }

  float acRed = sqrt(acRedSum / SPO2_BUF_SIZE);
  float acIR = sqrt(acIRSum / SPO2_BUF_SIZE);
  if (acIR < 0.001) return 0.0;

  float R = (acRed / dcRed) / (acIR / dcIR);
  float spo2 = 110.0f - 25.0f * R;
  return constrain(spo2, 0.0, 100.0);
}

void tmp117_readTemp() {
  Wire.beginTransmission(TMP117_ADDR);
  Wire.write(TMP117_REG_TEMP);
  if (Wire.endTransmission() == 0) {
    Wire.requestFrom(TMP117_ADDR, 2);
    if (Wire.available() >= 2) {
      int16_t raw = (Wire.read() << 8) | Wire.read();
      skinTempC = raw * 0.0078125f;
      skinTempF = (skinTempC * 1.8) + 32.0;
    }
  }
}

// =============================================================================
//  UI DRAWING FUNCTIONS - UNCHANGED
// =============================================================================
void drawStaticUI() {
  tft.fillScreen(C_BG);

  tft.fillRect(0, 0, 240, 24, 0x0861);
  tft.setTextSize(1); tft.setTextColor(C_LABEL);
  tft.setCursor(12, 8); tft.print("BIOMONITOR");
  tft.fillCircle(220, 12, 4, C_BLE);
  tft.setTextColor(C_BLE);
  tft.setCursor(193, 8); tft.print("USB");

  tft.drawFastHLine(0, 24, 240, C_DIV);

  tft.fillRect(0,   25, 120, 80, 0x0861);
  tft.fillRect(120, 25, 120, 80, 0x0861);
  tft.setTextColor(C_LABEL);
  tft.setCursor(12,  32); tft.print("HEART RATE");
  tft.setCursor(132, 32); tft.print("SpO2");

  tft.fillRoundRect(132, 90, 72, 3, 1, C_SPO2_DIM);

  tft.drawFastVLine(120, 25, 80, C_DIV);
  tft.drawFastHLine(0, 105, 240, C_DIV);

  tft.fillRect(0, 106, 240, 52, 0x0841);
  tft.setTextColor(C_LABEL);
  tft.setCursor(12, 113); tft.print("STRESS LEVEL");
  tft.fillRoundRect(12, 126, 172, 8, 4, 0x1082);
  tft.setTextColor(C_DIV);
  tft.setCursor(12,  148); tft.print("LOW");
  tft.setCursor(88,  148); tft.print("MED");
  tft.setCursor(167, 148); tft.print("HIGH");

  tft.drawFastHLine(0, 158, 240, C_DIV);

  tft.fillRect(0,   159, 120, 62, 0x0861);
  tft.fillRect(120, 159, 120, 62, 0x0861);
  tft.setTextColor(C_LABEL);
  tft.setCursor(12,  166); tft.print("HRV");
  tft.setCursor(132, 166); tft.print("SKIN TEMP");

  tft.drawFastVLine(120, 158, 63, C_DIV);
  tft.drawFastHLine(0, 221, 240, C_DIV);

  tft.fillRect(0, 222, 240, 58, C_BG);
  tft.setTextColor(C_LABEL);
  tft.setCursor(12, 229); tft.print("MOTION");
  tft.fillRoundRect(12,  241, 50, 4, 2, 0x1082);
  tft.fillRoundRect(78,  241, 50, 4, 2, 0x1082);
  tft.fillRoundRect(144, 241, 50, 4, 2, 0x1082);
}

void updateDisplay(float stress, int hr, float spo2, float hrv, float temp) {
  tft.fillRect(12, 44, 102, 52, 0x0861);
  tft.setTextColor(C_HR);
  if (hr > 0) {
    tft.setTextSize(4);
    tft.setCursor(hr >= 100 ? 12 : 22, 46);
    tft.print(hr);
    tft.setTextSize(1);
    tft.setTextColor(C_HR_DIM);
    tft.setCursor(hr >= 100 ? 76 : 64, 76);
    tft.print("bpm");
  } else {
    tft.setTextSize(3); tft.setCursor(22, 52); tft.print("--");
  }

  tft.fillRect(132, 44, 96, 44, 0x0861);
  tft.setTextColor(C_SPO2);
  if (spo2 > 0) {
    tft.setTextSize(4);
    tft.setCursor(132, 46);
    tft.printf("%.0f", spo2);
    tft.setTextSize(1);
    tft.setTextColor(C_SPO2_DIM);
    tft.setCursor(195, 76); tft.print("%");
    tft.fillRoundRect(132, 90, 72, 3, 1, C_SPO2_DIM);
    int bw = constrain((int)(spo2 / 100.0f * 70), 0, 70);
    tft.fillRoundRect(132, 90, bw, 3, 1, C_SPO2);
  } else {
    tft.setTextSize(3); tft.setCursor(140, 52); tft.print("--");
  }

  tft.fillRoundRect(12, 126, 172, 8, 4, 0x1082);
  uint16_t sCol = (stress < 0.35f) ? C_STRESS : (stress < 0.65f) ? C_STRESS_MID : C_STRESS_HI;
  int sw = constrain((int)(stress * 170), 0, 170);
  if (sw > 0) tft.fillRoundRect(12, 126, sw, 8, 4, sCol);
  tft.fillRect(192, 113, 46, 16, C_BG);
  tft.setTextColor(sCol);
  tft.setTextSize(1);
  tft.setCursor(192, 118);
  tft.printf("%.0f%%", stress * 100.0f);

  tft.fillRect(12, 175, 106, 40, 0x0861);
  tft.setTextColor(C_HRV);
  if (hrv > 0) {
    tft.setTextSize(3); tft.setCursor(12, 178);
    tft.printf("%.0f", hrv);
    tft.setTextSize(1);
    tft.setTextColor(C_HRV_DIM);
    tft.setCursor(hrv >= 100 ? 64 : 46, 196); tft.print("ms");
  } else {
    tft.setTextSize(3); tft.setCursor(12, 178); tft.print("--");
  }

  tft.fillRect(132, 175, 106, 40, 0x0861);
  tft.setTextColor(C_TEMP);
  if (temp > 0) {
    tft.setTextSize(2); tft.setCursor(132, 182);
    tft.printf("%.1f", temp);
    tft.setTextSize(1);
    tft.setTextColor(C_TEMP_DIM);
    tft.setCursor(214, 188); tft.print("F");
  } else {
    tft.setTextSize(2); tft.setCursor(132, 182); tft.print("--.-");
  }

  tft.fillRoundRect(12, 241, 50, 4, 2, 0x1082);
  int xw = constrain((int)(abs(mpu6050.getAccX()) * 50), 0, 50);
  tft.fillRoundRect(12, 241, xw, 4, 2, C_MOTION);
  tft.fillRect(12, 251, 64, 10, C_BG);
  tft.setTextColor(C_LABEL); tft.setTextSize(1);
  tft.setCursor(12, 253); tft.printf("X %.2f", mpu6050.getAccX());

  tft.fillRoundRect(78, 241, 50, 4, 2, 0x1082);
  int yw = constrain((int)(abs(mpu6050.getAccY()) * 50), 0, 50);
  tft.fillRoundRect(78, 241, yw, 4, 2, C_MOTION);
  tft.fillRect(78, 251, 64, 10, C_BG);
  tft.setCursor(78, 253); tft.printf("Y %.2f", mpu6050.getAccY());

  tft.fillRoundRect(144, 241, 50, 4, 2, 0x1082);
  int zw = constrain((int)(abs(mpu6050.getAccZ()) * 50), 0, 50);
  tft.fillRoundRect(144, 241, zw, 4, 2, C_MOTION);
  tft.fillRect(144, 251, 96, 10, C_BG);
  tft.setCursor(144, 253); tft.printf("Z %.2f", mpu6050.getAccZ());

  tft.fillRect(0, 264, 240, 16, C_BG);
  tft.setTextColor(C_LABEL);
  tft.setCursor(12, 267); tft.print("GSR");
  tft.setTextColor(0x6B6D);
  tft.setCursor(38, 267); tft.printf("%.1f k", currentRes);
  tft.setTextColor(C_LABEL);
  tft.setCursor(130, 267); tft.print("BASE");
  tft.setTextColor(0x6B6D);
  tft.setCursor(158, 267); tft.printf("%.1f k", baselineRes);

  static bool blinkState = false;
  blinkState = !blinkState;
  tft.fillCircle(220, 12, 4, blinkState ? C_BLE : 0x0841);
}

// =============================================================================
//  SETUP
// =============================================================================
void setup() {
  Serial.begin(115200);

  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);

  pinMode(MAX_INT, INPUT_PULLUP);

  mpu6050.begin();
  mpu6050.calcGyroOffsets(true);

  if (particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    particleSensor.setup();
    particleSensor.setPulseAmplitudeRed(0x3F);
    particleSensor.setPulseAmplitudeGreen(0);
  } else {
    Serial.println("MAX30102 Not Found!");
  }

  Wire.beginTransmission(TMP117_ADDR);
  if (Wire.endTransmission() == 0) tmp117Found = true;

  pinMode(GSR_CS, OUTPUT);
  digitalWrite(GSR_CS, HIGH);

  SPI.begin();
  tft.init(240, 280);
  tft.setRotation(0);
  drawStaticUI();

  float sum = 0;
  for(int i = 0; i < 100; i++) {
    sum += getResistance();
    delay(10);
  }
  baselineRes = sum / 100.0;

  Serial.println("ESP32 biomonitor ready");
}

// =============================================================================
//  MAIN LOOP
// =============================================================================
void loop() {
  unsigned long currentMillis = millis();

  if (digitalRead(MAX_INT) == LOW) {
    long irValue = particleSensor.getIR();
    long redValue = particleSensor.getRed();
    fingerDetected = (irValue > 50000);

    if (fingerDetected) {
      irBuffer[spo2BufIndex] = (uint32_t)irValue;
      redBuffer[spo2BufIndex] = (uint32_t)redValue;
      spo2BufIndex++;
      if (spo2BufIndex >= SPO2_BUF_SIZE) {
        spo2BufIndex = 0;
        spo2BufFull = true;
      }

      if (checkForBeat(irValue) == true) {
        long delta = currentMillis - lastBeat;
        lastBeat = currentMillis;
        beatsPerMinute = 60 / (delta / 1000.0);

        if (beatsPerMinute < 255 && beatsPerMinute > 20) {
          rates[rateSpot++] = (byte)beatsPerMinute;
          rateSpot %= RATE_SIZE;
          beatAvg = 0;
          for (byte x = 0; x < RATE_SIZE; x++) beatAvg += rates[x];
          beatAvg /= RATE_SIZE;
          updateHRV((float)delta);
        }
      }
    } else {
      beatAvg = 0;
      spo2Value = 0;
      hrvRMSSD = 0;
    }
  }

  if (currentMillis - lastTftUpdate >= 50) {
    lastTftUpdate = currentMillis;
    mpu6050.update();
    currentRes = getResistance();
    calculateStress(currentRes);
    updateDisplay(smoothStress, beatAvg, spo2Value, hrvRMSSD, skinTempF);
  }

  if (currentMillis - lastSerialReport >= 2000) {
    lastSerialReport = currentMillis;

    if (fingerDetected) spo2Value = calculateSpO2();
    if (tmp117Found) tmp117_readTemp();

    Serial.print("DATA,");
    Serial.print(currentMillis);
    Serial.print(",");
    Serial.print(mpu6050.getAccX(), 2);
    Serial.print(",");
    Serial.print(mpu6050.getAccY(), 2);
    Serial.print(",");
    Serial.print(mpu6050.getAccZ(), 2);
    Serial.print(",");
    Serial.print(currentRes, 2);
    Serial.print(",");
    Serial.print(smoothStress, 3);
    Serial.print(",");
    Serial.print(beatAvg);
    Serial.print(",");
    Serial.print(spo2Value, 1);
    Serial.print(",");
    Serial.print(hrvRMSSD, 1);
    Serial.print(",");
    Serial.println(skinTempF, 2);
  }
}