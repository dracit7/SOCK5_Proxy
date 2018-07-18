import socket
import struct
import threading
import os

# Define 4 status of the HandShake period.
REFUSED=0 # Connection denied by this server.
TCP=1 # Build TCP connection with the remoteserver
UDP=2 # Build UDP association with the remoteserver
BIND=3 # Reversed Link (Not implemented yet)

MAX_BUFFER=1024 # The max size of the post recieved
MAX_CLIENT=3 # Maximum waiting clients num

class PostTransmitter(threading.Thread):
  '''
  Recieve post from a socket,and transmit it to another.
  '''
  def __init__(self,Sock_1,Sock_2):
    threading.Thread.__init__(self)
    self.AcceptSock=Sock_1
    self.SendSock=Sock_2
  def run(self):
    while True:
      try:
        Post=self.AcceptSock.recv(MAX_BUFFER)
        self.SendSock.send(Post)
      except BrokenPipeError:
        pass
      except ConnectionResetError:
        pass


def HandShake(Post):
  '''
  Handle the handshake period of server and client.
  ''' 
    # +-----+----------+----------+
    # | VER | NMETHODS | METHODS  |
    # +-----+----------+----------+
    # |  1  |    1     |  1~255   |
    # +-----+----------+----------+
  Version,MethodNum = struct.unpack('!BB',Post[:2])
  Post=Post[2:]
  Format='!'
  for i in range(0,MethodNum):
    Format+='B'
  Methods = struct.unpack(Format,Post)
  if 0 in Methods:
    Method=0x00 # No authentication needed yet
  else:
    Method=0xff
    # If client doesn't support no authentacation mode, refuse its request.
  Answer=struct.pack('!BB',Version,Method)
  return Answer

def Connect(Post):
  '''
  The second handshake with client.
  '''
    # +----+-----+-------+------+----------+----------+
    # |VER | CMD |  RSV  | ATYP | DST.ADDR | DST.PORT |
    # +----+-----+-------+------+----------+----------+
    # | 1  |  1  |   1   |  1   | Variable |    2     |
    # +----+-----+-------+------+----------+----------+

    # +----+-----+-------+------+----------+----------+
    # |VER | REP |  RSV  | ATYP | BND.ADDR | BND.PORT |
    # +----+-----+-------+------+----------+----------+
    # | 1  |  1  |   1   |  1   | Variable |    2     |
    # +----+-----+-------+------+----------+----------+

  PostInfo={}
  if Post != b'':
    PostInfo['Version'],PostInfo['Command'],PostInfo['RSV'],PostInfo['AddrType']\
    = struct.unpack('!BBBB',Post[:4])

  # AddressType:
  # 0x01 - IPv4
  # 0x03 - DomainName (not supported)
  # 0x04 - IPv6
  if PostInfo['AddrType'] == 0x01:
    Length=4
    # Parse RemoteServer's address by AddrType
    Format='!'+str(Length)+'sH'
    RawAddress,PostInfo['RemotePort']=struct.unpack(Format,Post[4:])
    PostInfo['RemoteAddress']=socket.inet_ntoa(RawAddress)
  elif PostInfo['AddrType'] == 0x04:
    Length=16
    # Parse RemoteServer's address by AddrType
    Format='!'+str(Length)+'sH'
    RawAddress,PostInfo['RemotePort']=struct.unpack(Format,Post[4:])
    PostInfo['RemoteAddress']=socket.inet_ntoa(RawAddress)
  elif PostInfo['AddrType'] == 0x03:
    Length,=struct.unpack('!B',Post[4:5])
    url,PostInfo['RemotePort']=struct.unpack('!'+str(Length)+'sH',Post[5:])
    PostInfo['Length']=Length
    PostInfo['url']=url
    PostInfo['RemoteAddress']=socket.gethostbyname(url)
  else:
    print('Error: Wrong address type.')
    PostInfo['REP']=0x08
    return (PostInfo,REFUSED)

  # Respond to Client's Command.
  if PostInfo['Command'] == 0x01:
    PostInfo['REP']=0x00
    return (PostInfo,TCP)
  elif PostInfo['Command'] == 0x02:
    PostInfo['REP']=0x08
    return (PostInfo,BIND)
  elif PostInfo['Command'] == 0x03:
    PostInfo['REP']=0x00
    return (PostInfo,UDP)
  else:
    PostInfo['REP']=0x02
    return (PostInfo,REFUSED)
    
class TCPHandler(threading.Thread):
  '''
  Communicate with one single Client.
  '''
  def __init__(self,ClientSock):
    threading.Thread.__init__(self)
    self.ClientSock=ClientSock
  def run(self):
    # First Handshake
    Post=self.ClientSock.recv(MAX_BUFFER)
    self.ClientSock.send(HandShake(Post))
    # Second Handshake,gain information.
    PostInfo,Status=Connect(self.ClientSock.recv(MAX_BUFFER))

    # Judge Status
    if Status == REFUSED:
      # If server refuses client's request,send the answer and close the socket.
      print('Request refused.')
      Answer=struct.pack('!BBBB',\
      PostInfo['Version'],PostInfo['REP'],PostInfo['RSV'],PostInfo['AddrType'])
      self.ClientSock.send(Answer)
      self.ClientSock.close()
      return
    else:
      # Assemble the answer
      if PostInfo['AddrType'] == 0x01:
        Length=4
        Answer=struct.pack('!BBBB'+str(Length)+'sH',\
        PostInfo['Version'],PostInfo['REP'],PostInfo['RSV'],PostInfo['AddrType'],\
        socket.inet_aton(PostInfo['RemoteAddress']),PostInfo['RemotePort'])
      elif PostInfo['AddrType'] == 0x04:
        Length=16
        Answer=struct.pack('!BBBB'+str(Length)+'sH',\
        PostInfo['Version'],PostInfo['REP'],PostInfo['RSV'],PostInfo['AddrType'],\
        socket.inet_aton(PostInfo['RemoteAddress']),PostInfo['RemotePort'])
      elif PostInfo['AddrType'] == 0x03:
        Answer=struct.pack('!BBBBB'+str(PostInfo['Length'])+'sH',\
        PostInfo['Version'],PostInfo['REP'],PostInfo['RSV'],PostInfo['AddrType'],\
        PostInfo['Length'],PostInfo['url'],PostInfo['RemotePort'])
      else:
        Length=0
      
      # Connect or associate with the remote server.
      if Status == TCP:
        try:
          RemoteSock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
          RemoteSock.connect((PostInfo['RemoteAddress'],PostInfo['RemotePort']))
        except ConnectionRefusedError:
          print('Error: Connection refused.')
          RemoteSock.close()
        else:
          self.ClientSock.send(Answer)
          SendThread=PostTransmitter(self.ClientSock,RemoteSock)
          AcceptThread=PostTransmitter(RemoteSock,self.ClientSock)
          SendThread.start()
          AcceptThread.start()
          # RAM leakage warning
      elif Status == UDP:
        RemoteSock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        self.ClientSock.send(Answer)
      else:
        self.ClientSock.send(Answer)
        self.ClientSock.close()
        return


 
      

if __name__ == '__main__':
  ServerSock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
  print('Welcome !\n')
  print('Please input the IP address and port you want to bind with.')
  try:
    Address=input('IP address:')
    Port=input('Port:')
  except KeyboardInterrupt:
    print('\n\nbye bye.\n')
    os.sys.exit()
  print("\nWaiting for connection ...\n")
  try:
    ServerSock.bind((Address,int(Port)))
    ServerSock.listen(MAX_CLIENT)
    while True:
      CliSock,CliAddr=ServerSock.accept()
      Thread=TCPHandler(CliSock)
      Thread.start()
  except OSError:
    print("Error: Address already in use. Please use another port.")
    os.sys.exit()
  except KeyboardInterrupt:
    print('\n\nbye bye.\n')
    os.sys.exit()
  finally:
    ServerSock.close()


  
  
  