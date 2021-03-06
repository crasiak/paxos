'''
This module provides a minimal implementation of the Paxos algorithm that
explicitly decouples all external messaging concerns from the algortihm
internals. These classes may be used as-is to provide correctness to
network-aware applications that enhance the basic Paxos model with
such things as timeouts, retransmits, and liveness-detectors.
'''


class Messenger (object):
    def send_prepare(self, proposal_id):
        '''
        Broadcasts a Prepare message to all nodes
        '''

    def send_promise(self, to_uid, proposal_id, previous_id, accepted_value):
        '''
        Sends a Promise message to the specified node
        '''

    def send_prepare_nack(self, to_uid, proposal_id, promised_id):
        '''
        Sends a Prepare Nack message for the proposal to the specified node
        '''

    def send_accept(self, proposal_id, proposal_value):
        '''
        Broadcasts an Accept! message to all nodes
        '''

    def send_accept_nack(self, to_uid, proposal_id, promised_id):
        '''
        Sends a Accept! Nack message for the proposal to the specified node
        '''

    def send_accepted(self, to_uid, proposal_id, accepted_value):
        '''
        Broadcasts an Accepted message to all nodes
        '''

    def on_leadership_acquired(self):
        '''
        Called when leadership has been aquired. This is not a guaranteed
        position. Another node may assume leadership at any time and it's
        even possible that another may have successfully done so before this
        callback is exectued. Use this method with care.

        The safe way to guarantee leadership is to use a full Paxos instance
        whith the resolution value being the UID of the leader node. To avoid
        potential issues arising from timing and/or failure, the election
        result may be restricted to a certain time window. Prior to the end of
        the window the leader may attempt to re-elect itself to extend it's
        term in office.
        '''

    def on_resolution(self, proposal_id, value):
        '''
        Called when a resolution is reached
        '''



class Proposer (object):

    messenger            = None
    node_uid             = None
    quorum_size          = None

    proposed_value       = None
    proposal_id          = None # tuple of (proposal_number, node_uid)
    last_accepted_id     = None
    next_proposal_number = 1
    promises_rcvd        = None
    leader               = False

    
    def set_proposal(self, value):
        '''
        Sets the proposal value for this node iff this node is not already aware of
        another proposal having already been accepted. 
        '''
        if self.proposed_value is None:
            self.proposed_value = value

            if self.leader:
                self.messenger.send_accept( self.proposal_id, value )


    def prepare(self, increment_proposal_number=True):
        '''
        Sends a prepare request to all nodes as the first step in attempting to
        acquire leadership of the Paxos instance. If the default argument is True,
        the proposal id will be set higher than that of any previous observed
        proposal id. Otherwise the previously used proposal id will simply be
        retransmitted.
        
        The proposal id is a tuple of (proposal_numer, node_uid)
        '''
        if increment_proposal_number:
            self.leader        = False
            self.promises_rcvd = set()
            self.proposal_id   = (self.next_proposal_number, self.node_uid)
        
            self.next_proposal_number += 1

        self.messenger.send_prepare(self.proposal_id)

    
    def observe_proposal(self, from_uid, proposal_id):
        '''
        Optional method used to update the proposal counter as proposals are seen on the network.
        When co-located with Acceptors and/or Learners, this method may be used to avoid a message
        delay when attempting to assume leadership (guaranteed NACK if the proposal number is too low).
        '''
        if from_uid != self.node_uid:
            if proposal_id >= (self.next_proposal_number, self.node_uid):
                self.next_proposal_number = proposal_id[0] + 1

            
    def recv_prepare_nack(self, from_uid, proposal_id, promised_id):
        '''
        Called when an explicit NACK is sent in response to a prepare message.
        '''
        self.observe_proposal( from_uid, promised_id )

    
    def recv_accept_nack(self, from_uid, proposal_id, promised_id):
        '''
        Called when an explicit NACK is sent in response to an accept message
        '''

        
    def resend_accept(self):
        '''
        Retransmits an Accept! message iff this node is the leader and has
        a proposal value
        '''
        if self.leader and self.proposed_value:
            self.messenger.send_accept(self.proposal_id, self.proposed_value)


    def recv_promise(self, from_uid, proposal_id, prev_accepted_id, prev_accepted_value):
        '''
        Called when a Promise message is received from the network
        '''
        if proposal_id > (self.next_proposal_number-1, self.node_uid):
            self.next_proposal_number = proposal_id[0] + 1

        if self.leader or proposal_id != self.proposal_id or from_uid in self.promises_rcvd:
            return

        self.promises_rcvd.add( from_uid )
        
        if prev_accepted_id > self.last_accepted_id:
            self.last_accepted_id = prev_accepted_id
            # Only override the current proposal value if the acceptor has
            # accepted one. "None" is not a valid value
            if prev_accepted_value is not None:
                self.proposed_value = prev_accepted_value

        if len(self.promises_rcvd) == self.quorum_size:
            self.leader = True

            self.messenger.on_leadership_acquired()
            
            if self.proposed_value is not None:
                self.messenger.send_accept(self.proposal_id, self.proposed_value)
            



        
class Acceptor (object):

    messenger      = None
    
    promised_id    = None
    accepted_value = None
    accepted_id    = None
    previous_id    = None


    def recv_prepare(self, from_uid, proposal_id):
        '''
        Called when a Prepare message is received from the network
        '''
        if proposal_id == self.promised_id:
            # Duplicate accepted proposal
            self.messenger.send_promise(from_uid, proposal_id, self.previous_id, self.accepted_value)
        
        elif proposal_id > self.promised_id:
            self.previous_id = self.promised_id            
            self.promised_id = proposal_id
            self.messenger.send_promise(from_uid, proposal_id, self.previous_id, self.accepted_value)

        else:
            self.messenger.send_prepare_nack(from_uid, proposal_id, self.promised_id)

                    
    def recv_accept_request(self, from_uid, proposal_id, value):
        '''
        Called when an Accept! message is received from the network
        '''
        if proposal_id >= self.promised_id:
            self.accepted_value  = value
            self.promised_id     = proposal_id
            self.messenger.send_accepted(from_uid, proposal_id, self.accepted_value)
        else:
            self.messenger.send_accept_nack(from_uid, proposal_id, self.promised_id)
        


        
class Learner (object):

    quorum_size       = None

    proposals         = None # maps proposal_id => [accept_count, retain_count, value]
    acceptors         = None # maps from_uid => last_accepted_proposal_id
    final_value       = None
    final_proposal_id = None


    @property
    def complete(self):
        return self.final_proposal_id is not None


    def recv_accepted(self, from_uid, proposal_id, accepted_value):
        '''
        Called when an Accepted message is received from the network.
        '''
        if self.final_value is not None:
            return # already done

        if self.proposals is None:
            self.proposals = dict()
            self.acceptors = dict()
        
        last_pn = self.acceptors.get(from_uid)

        if not proposal_id > last_pn:
            return # Old message

        self.acceptors[ from_uid ] = proposal_id
        
        if last_pn is not None:
            oldp = self.proposals[ last_pn ]
            oldp[1] -= 1
            if oldp[1] == 0:
                del self.proposals[ last_pn ]

        if not proposal_id in self.proposals:
            self.proposals[ proposal_id ] = [0, 0, accepted_value]

        t = self.proposals[ proposal_id ]

        assert accepted_value == t[2], 'Value mismatch for single proposal!'
        
        t[0] += 1
        t[1] += 1

        if t[0] == self.quorum_size:
            self.final_value       = accepted_value
            self.final_proposal_id = proposal_id
            self.proposals         = None
            self.acceptors         = None

            self.messenger.on_resolution( proposal_id, accepted_value )
            

    
class Node (Proposer, Acceptor, Learner):
    '''
    This class supports the common model where each node on a network preforms
    all three Paxos roles, Proposer, Acceptor, and Learner.
    '''

    def __init__(self, messenger, node_uid, quorum_size):
        self.messenger   = messenger
        self.node_uid    = node_uid
        self.quorum_size = quorum_size
            

    def __getstate__(self):
        pstate = dict( self.__dict__ )
        del pstate['messenger']
        return pstate

    
    def recover(self, messenger):
        '''
        Required after unpickling a Node object to re-establish the
        messenger attribute
        '''
        self.messenger = messenger

        
    def change_quorum_size(self, quorum_size):
        self.quorum_size = quorum_size

        
    def recv_prepare(self, from_uid, proposal_id):
        self.observe_proposal( from_uid, proposal_id )
        return super(Node,self).recv_prepare( from_uid, proposal_id )


