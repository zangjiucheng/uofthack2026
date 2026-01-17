"""
Robot Control API - High-level interface for bot control system
Communicates with ESP32 control board via UART at /dev/ttyAMA0 921600

Simplified API supporting:
- Motors (left/right speed control)
- Head (yaw/pitch servo control)
- Battery (voltage monitoring)
"""

import serial
import time
import threading
import board
import busio
import adafruit_vl53l0x
import adafruit_ssd1306
from PIL import Image, ImageDraw, ImageFont


class SerialConnection:
    """Low-level serial communication handler"""
    
    def __init__(self, port: str = "/dev/ttyAMA0", baudrate: int = 921600, timeout: float = 1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self._lock = threading.Lock()
    
    def connect(self) -> bool:
        """Connect to serial port"""
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                write_timeout=self.timeout
            )
            time.sleep(0.5)  # Wait for device to stabilize
            return True
        except Exception as e:
            print(f"Failed to connect to {self.port}: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from serial port"""
        if self.ser and self.ser.is_open:
            self.ser.close()
    
    def send_command(self, command: str) -> str:
        """Send command and get response"""
        if not self.ser or not self.ser.is_open:
            raise RuntimeError("Serial port not connected")
        
        with self._lock:
            try:
                # Send command with newline
                self.ser.write((command + "\n").encode())
                self.ser.flush()
                
                # Read response
                response = self.ser.readline().decode('utf-8', errors='ignore').strip()
                return response
            except Exception as e:
                raise RuntimeError(f"Serial communication error: {e}")




class Motors:

    """Motor control interface"""
    
    def __init__(self, serial_conn: SerialConnection):
        self.serial = serial_conn
        self._left_axis = "m.l"
        self._right_axis = "m.r"
    
    def __repr__(self) -> str:
        """Display motor status"""
        try:
            left_rps = self.left
            right_rps = self.right
            enabled = self.enabled
            return f"Motors(left={left_rps:.3f} RPS, right={right_rps:.3f} RPS, enabled={enabled})"
        except Exception as e:
            return f"Motors(error: {e})"
    
    @property
    def left(self) -> float:
        """Get left motor speed in revolutions per second"""
        response = self.serial.send_command(f"get {self._left_axis}")
        try:
            value = float(response.split('=')[1].split()[0])
            return value
        except (IndexError, ValueError):
            raise ValueError(f"Failed to parse left motor speed: {response}")
    
    @left.setter
    def left(self, value: float) -> None:
        """Set left motor speed in revolutions per second"""
        self.serial.send_command(f"set {self._left_axis} {value}")
    
    @property
    def right(self) -> float:
        """Get right motor speed in revolutions per second"""
        response = self.serial.send_command(f"get {self._right_axis}")
        try:
            value = float(response.split('=')[1].split()[0])
            return value
        except (IndexError, ValueError):
            raise ValueError(f"Failed to parse right motor speed: {response}")
    
    @right.setter
    def right(self, value: float) -> None:
        """Set right motor speed in revolutions per second"""
        self.serial.send_command(f"set {self._right_axis} {value}")

    
    @property
    def enabled(self) -> bool:
        """Check if motors are enabled (fetched from device)"""
        response = self.serial.send_command("get m.en")
        # Parse response like "m.en = 1"
        try:
            value = int(response.split('=')[1].strip())
            return value == 1
        except (IndexError, ValueError):
            raise ValueError(f"Failed to parse motor enable state: {response}")
    
    @enabled.setter
    def enabled(self, value: bool):
        """Enable/disable motors (lock stepper motors)"""
        cmd_value = 1 if value else 0
        self.serial.send_command(f"set m.en {cmd_value}")


class Eye:
    """Single eye with OLED display"""
    
    def __init__(self, i2c: busio.I2C, address: int):
        self.address = address
        self.display = None
        
        try:
            self.display = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=address)
            # Clear display
            self.display.fill(0)
            self.display.show()
        except Exception as e:
            print(f"Warning: OLED display at 0x{address:02x} initialization failed: {e}")
            self.display = None
    
    def __repr__(self) -> str:
        """Display eye status"""
        status = "OK" if self.display else "ERROR"
        return f"Eye(0x{self.address:02x}, {status})"


class Eyes:
    """Dual eye displays"""
    
    def __init__(self, i2c: busio.I2C):
        self.left = Eye(i2c, 0x3c)
        self.right = Eye(i2c, 0x3d)
    
    def __repr__(self) -> str:
        """Display eyes status"""
        return f"Eyes(left={self.left.display is not None}, right={self.right.display is not None})"


class Head:
    """Head/camera gimbal control with distance sensor"""
    
    def __init__(self, serial_conn: SerialConnection, i2c: busio.I2C = None):
        self.serial = serial_conn
        self.i2c = i2c
        
        # Initialize distance sensor
        self.sensor = None
        self._sensor_available = False
        
        if i2c:
            try:
                self.sensor = adafruit_vl53l0x.VL53L0X(i2c)
                self._sensor_available = True
            except Exception as e:
                print(f"Warning: Distance sensor initialization failed: {e}")
                self._sensor_available = False
    
    def __repr__(self) -> str:
        """Display head position"""
        try:
            yaw = self.yaw
            pitch = self.pitch
            distance_info = ""
            if self._sensor_available:
                distance_info = f", distance={self.distance:.2f}m"
            return f"Head(yaw={yaw:.1f}°, pitch={pitch:.1f}°{distance_info})"
        except Exception as e:
            return f"Head(error: {e})"
    
    @property
    def distance(self) -> float:
        """Get distance reading from VL53L0X sensor in meters"""
        if not self._sensor_available or self.sensor is None:
            raise RuntimeError("Distance sensor not available")
        try:
            distance_mm = self.sensor.range
            return distance_mm / 1000.0
        except Exception as e:
            raise RuntimeError(f"Failed to read distance sensor: {e}")
    
    @property
    def yaw(self) -> float:
        """Get head yaw angle (+ for right, - for left) in degrees (fetched from device)"""
        response = self.serial.send_command("get head.yaw")
        # Parse response like "head.yaw = 0.00°"
        try:
            value = float(response.split('=')[1].split()[0])
            return value
        except (IndexError, ValueError):
            raise ValueError(f"Failed to parse head yaw response: {response}")
    
    @yaw.setter
    def yaw(self, value: float):
        """Set head yaw angle in degrees"""
        self.serial.send_command(f"set head.yaw {value}")
    
    @property
    def pitch(self) -> float:
        """Get head pitch angle (+ for look up, - for look down) in degrees (fetched from device)"""
        response = self.serial.send_command("get head.pitch")
        # Parse response like "head.pitch = 0.00°"
        try:
            value = float(response.split('=')[1].split()[0])
            return value
        except (IndexError, ValueError):
            raise ValueError(f"Failed to parse head pitch response: {response}")
    
    @pitch.setter
    def pitch(self, value: float):
        """Set head pitch angle in degrees"""
        self.serial.send_command(f"set head.pitch {value}")


class Battery:
    """Battery monitoring"""
    
    def __init__(self, serial_conn: SerialConnection):
        self.serial = serial_conn
    
    def __repr__(self) -> str:
        """Display battery status"""
        try:
            voltage = self.voltage
            cells = self.cells
            cell_voltage = self.cell_voltage
            percentage = self.percentage
            return f"Battery({voltage:.2f}V, {cells}S, {cell_voltage:.3f}V/cell, {percentage:.0f}%)"
        except Exception as e:
            return f"Battery(error: {e})"
    
    @property
    def cells(self) -> int:
        """Get number of battery cells detected"""
        response = self.serial.send_command("get batt.cells")
        # Parse response like "batt.cells = 3"
        try:
            value = int(response.split('=')[1].strip())
            return value
        except (IndexError, ValueError):
            return 0
    
    @property
    def voltage(self) -> float:
        """Get total battery voltage in volts"""
        response = self.serial.send_command("get batt.voltage")
        # Parse response like "batt.voltage = 12.500 V"
        try:
            value = float(response.split('=')[1].split()[0])
            return value
        except (IndexError, ValueError):
            return 0.0
    
    @property
    def cell_voltage(self) -> float:
        """Get voltage per cell in volts"""
        response = self.serial.send_command("get batt.cell_voltage")
        # Parse response like "batt.cell_voltage = 4.167 V"
        try:
            value = float(response.split('=')[1].split()[0])
            return value
        except (IndexError, ValueError):
            return 0.0
    
    @property
    def percentage(self) -> float:
        """Get battery percentage (0-100)"""
        response = self.serial.send_command("get batt.percentage")
        # Parse response like "batt.percentage = 85.00 %"
        try:
            value = float(response.split('=')[1].split()[0])
            return value
        except (IndexError, ValueError):
            return 0.0


class Bot:
    """Main robot control interface
    
    Usage:
        bot = Bot()
        bot.motors.left.rps = 0.5
        bot.motors.right.rps = 0.5
        bot.motors.enabled = True
        bot.head.yaw = 45
        bot.head.pitch = 0
        print(bot.battery.voltage)
    """
    
    def __init__(self, port: str = "/dev/ttyAMA0", baudrate: int = 921600):
        """Initialize robot connection
        
        Args:
            port: Serial port (default: /dev/ttyAMA0 for Raspberry Pi)
            baudrate: Serial baudrate (default: 921600)
        """
        self.serial = SerialConnection(port, baudrate)
        
        if not self.serial.connect():
            raise RuntimeError(f"Failed to connect to robot at {port}")
        
        # Initialize I2C for sensors and displays
        i2c = None
        try:
            i2c = busio.I2C(board.SCL, board.SDA)
        except Exception as e:
            print(f"Warning: I2C initialization failed: {e}")
        
        # Initialize sub-components
        self.motors = Motors(self.serial)
        self.head = Head(self.serial, i2c)
        self.eyes = Eyes(i2c) if i2c else None
        self.battery = Battery(self.serial)
    
    def disconnect(self):
        """Disconnect from robot"""
        self.serial.disconnect()
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()




if __name__ == "__main__":
    # Example usage
    try:
        bot = Bot()
        
        print("=== Robot Control API Test ===")
        print(f"Battery: {bot.battery.voltage:.2f}V ({bot.battery.cells} cells)")
        print(f"Battery cell voltage: {bot.battery.cell_voltage:.3f}V")
        print(f"Battery percentage: {bot.battery.percentage:.1f}%")
        
        print("\n=== Motor Control ===")
        bot.motors.enabled = True
        bot.motors.left.rps = 0.1
        bot.motors.right.rps = 0.1
        print(f"Left motor: {bot.motors.left.rps} RPS")
        print(f"Right motor: {bot.motors.right.rps} RPS")
        
        time.sleep(2)
        
        bot.motors.left.rps = 0
        bot.motors.right.rps = 0
        bot.motors.enabled = False
        
        print("\n=== Head Control ===")
        bot.head.yaw = 45
        bot.head.pitch = 0
        print(f"Head yaw: {bot.head.yaw}°")
        print(f"Head pitch: {bot.head.pitch}°")
        
        bot.disconnect()
        print("\n✓ Test completed successfully")
        
    except Exception as e:
        print(f"Error: {e}")
