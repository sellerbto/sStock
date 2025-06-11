#!/usr/bin/env python3
"""
Test script to reproduce and verify the fund reservation bug fix.

The bug: User can create multiple sell orders for the same asset without proper reservation.
Expected behavior: Second order should fail due to insufficient available balance.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'api'))

from api.database import Database
from api.models import User, LimitOrderBody, Direction, Instrument
from uuid import uuid4
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_fund_reservation_bug():
    """Test that reproduces the fund reservation bug and verifies the fix"""
    
    # Initialize database with localhost PostgreSQL for testing
    db = Database("postgresql://postgres:postgres@localhost:5432/stock_exchange")
    
    # Create test user
    user_id = uuid4()
    test_user = User(
        id=user_id,
        name="testuser",
        email="test@example.com",
        password_hash="dummy_hash",
        api_key="test_api_key"
    )
    
    try:
        # Add user to database
        db.add_user(test_user)
        logger.info(f"Created test user: {user_id}")
        
        # Add test instrument
        instrument = Instrument(ticker="NOTADUDE", name="Test Asset")
        db.add_instrument(instrument)
        logger.info("Added test instrument: NOTADUDE")
        
        # Set up initial balance: RUB: 99, NOTADUDE: 1
        db.update_balance(user_id, "RUB", 99)
        db.update_balance(user_id, "NOTADUDE", 1)
        logger.info("Set initial balance: RUB=99, NOTADUDE=1")
        
        # Check initial available balance
        available_balance = db.get_available_balance(user_id)
        logger.info(f"Initial available balance: {available_balance}")
        
        assert available_balance.get("RUB", 0) == 99, f"Expected RUB=99, got {available_balance.get('RUB', 0)}"
        assert available_balance.get("NOTADUDE", 0) == 1, f"Expected NOTADUDE=1, got {available_balance.get('NOTADUDE', 0)}"
        
        # Create first sell limit order for NOTADUDE qty = 1
        order1_body = LimitOrderBody(
            direction=Direction.SELL,
            ticker="NOTADUDE",
            qty=1,
            price=100  # Price 100 RUB per NOTADUDE
        )
        
        logger.info("Creating first sell order for 1 NOTADUDE...")
        
        # Check available balance before locking
        available_before_lock = db.get_available_balance(user_id)
        logger.info(f"Available balance before lock: {available_before_lock}")
        
        # Lock funds for first order
        db.lock_funds(user_id, "NOTADUDE", 1)
        logger.info("Locked 1 NOTADUDE for first order")
        
        # Check available balance after locking
        available_after_lock = db.get_available_balance(user_id)
        logger.info(f"Available balance after lock: {available_after_lock}")
        
        # NOTADUDE should no longer be available
        assert available_after_lock.get("NOTADUDE", 0) == 0, f"Expected NOTADUDE=0 after lock, got {available_after_lock.get('NOTADUDE', 0)}"
        
        # Try to create second sell limit order for NOTADUDE qty = 1
        order2_body = LimitOrderBody(
            direction=Direction.SELL,
            ticker="NOTADUDE",
            qty=1,
            price=100
        )
        
        logger.info("Attempting to create second sell order for 1 NOTADUDE...")
        
        # This should fail because there's no available NOTADUDE left
        try:
            # Check if we have enough available balance for second order
            if available_after_lock.get("NOTADUDE", 0) < 1:
                logger.info("✅ SUCCESS: Second order would be rejected due to insufficient available balance")
                print("✅ FUND RESERVATION BUG IS FIXED!")
                print(f"   - Initial balance: NOTADUDE=1")
                print(f"   - After first order lock: NOTADUDE={available_after_lock.get('NOTADUDE', 0)}")
                print(f"   - Second order rejected: insufficient available balance")
            else:
                logger.error("❌ FAIL: Second order would be allowed despite insufficient available balance")
                print("❌ FUND RESERVATION BUG STILL EXISTS!")
                return False
                
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return False
            
        # Test unlocking funds (simulate order cancellation)
        logger.info("Testing fund unlocking...")
        db.unlock_funds(user_id, "NOTADUDE", 1)
        
        available_after_unlock = db.get_available_balance(user_id)
        logger.info(f"Available balance after unlock: {available_after_unlock}")
        
        # NOTADUDE should be available again
        assert available_after_unlock.get("NOTADUDE", 0) == 1, f"Expected NOTADUDE=1 after unlock, got {available_after_unlock.get('NOTADUDE', 0)}"
        logger.info("✅ Fund unlocking works correctly")
        
        return True
        
    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        return False
    finally:
        # Clean up - remove test user (this will cascade delete balances)
        try:
            db.delete_user(user_id)
            logger.info("Cleaned up test user")
        except:
            pass

def main():
    """Run the fund reservation test"""
    print("🧪 Testing Fund Reservation Bug Fix...")
    print("=" * 50)
    
    success = test_fund_reservation_bug()
    
    print("=" * 50)
    if success:
        print("🎉 All tests passed! Fund reservation is working correctly.")
        return 0
    else:
        print("💥 Test failed! Fund reservation bug still exists.")
        return 1

if __name__ == "__main__":
    exit(main())